#!/usr/bin/env python3
"""
List newest Homebrew casks and popularity among them.

Default output:
1) Newest 100 casks (local-first recency index) with descriptions.
2) Top 25 popular among newest 250 (analytics window selectable).

Design:
- Local-first for metadata and recency updates.
- Bounded GitHub bootstrap only when local recency index is insufficient.
- Analytics cached locally with TTL and offline fallback.
"""

# Standard Library
import argparse
import datetime
import html
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

#============================================
# Constants

FORMULAE_API_BASE = "https://formulae.brew.sh/api"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_OWNER = "Homebrew"
GITHUB_REPO = "homebrew-cask"

WINDOWS = ("30d", "90d", "365d")
DEFAULT_ANALYTICS_WINDOW = "30d"
DEFAULT_ANALYTICS_TTL_HOURS = 24
DEFAULT_BOOTSTRAP_MAX_PAGES = 4
DEFAULT_BOOTSTRAP_MAX_DETAIL_REQUESTS = 120

DEFAULT_NEWEST_POOL_SIZE = 250
DEFAULT_NEWEST_PRINT_COUNT = 100
DEFAULT_POPULAR_PRINT_COUNT = 25
DEFAULT_REPORT_FILE = "homebrew_top_new_report.html"

LOCAL_CASK_PAYLOAD_NAME = "cask.jws.json"
LOCAL_CASK_NAMES_CURRENT = "cask_names.txt"
LOCAL_CASK_NAMES_BEFORE = "cask_names.before.txt"
STATE_FILE_NAME = "homebrew_top_new_state.json"

STATE_SCHEMA_VERSION = 1

#============================================
def now_utc() -> datetime.datetime:
	"""
	Return current UTC datetime.
	"""
	return datetime.datetime.now(datetime.timezone.utc)


#============================================
def to_iso(dt: datetime.datetime) -> str:
	"""
	Convert datetime to ISO string in UTC.
	"""
	utc_value = dt.astimezone(datetime.timezone.utc)
	return utc_value.replace(microsecond=0).isoformat()


#============================================
def parse_iso(text: str) -> datetime.datetime | None:
	"""
	Parse ISO datetime text.
	"""
	if not text:
		return None
	try:
		value = datetime.datetime.fromisoformat(text)
	except ValueError:
		return None
	if value.tzinfo is None:
		return value.replace(tzinfo=datetime.timezone.utc)
	return value.astimezone(datetime.timezone.utc)


#============================================
def run_command(args: list[str]) -> str:
	"""
	Run command and return stripped stdout.
	"""
	result = subprocess.run(
		args,
		capture_output=True,
		text=True,
	)
	if result.returncode != 0:
		message = result.stderr.strip() or f"Command failed: {' '.join(args)}"
		raise RuntimeError(message)
	return result.stdout.strip()


#============================================
def get_api_cache_dir() -> str:
	"""
	Resolve Homebrew API cache directory.
	"""
	cache_root = run_command(["brew", "--cache"])
	return os.path.join(cache_root, "api")


#============================================
def can_write_dir(path: str) -> bool:
	"""
	Return whether a directory is writable by creating/removing a probe file.
	"""
	if not os.path.isdir(path):
		return False
	probe_path = os.path.join(path, ".homebrew_top_new_write_probe")
	try:
		with open(probe_path, "w", encoding="utf-8") as handle:
			handle.write("probe\n")
		os.remove(probe_path)
	except OSError:
		return False
	return True


#============================================
def ensure_dir(path: str) -> bool:
	"""
	Create directory if missing and report success.
	"""
	try:
		os.makedirs(path, exist_ok=True)
	except OSError:
		return False
	return os.path.isdir(path)


#============================================
def get_work_dir(api_dir: str, warnings: list[str]) -> str:
	"""
	Resolve writable directory for state and analytics cache files.
	"""
	if can_write_dir(api_dir):
		return api_dir

	home_cache = os.path.join(os.path.expanduser("~"), ".cache", "homebrew_top_new")
	if ensure_dir(home_cache) and can_write_dir(home_cache):
		warnings.append(
			f"cache dir fallback: using {home_cache} for state/cache writes"
		)
		return home_cache

	cwd_cache = os.path.join(os.getcwd(), ".homebrew_top_new_cache")
	if ensure_dir(cwd_cache) and can_write_dir(cwd_cache):
		warnings.append(
			f"cache dir fallback: using {cwd_cache} for state/cache writes"
		)
		return cwd_cache

	raise RuntimeError("No writable directory found for state/cache files.")


#============================================
def get_json(url: str, headers: dict[str, str] | None = None, query: dict | None = None) -> object:
	"""
	Fetch JSON from URL.
	"""
	if query:
		query_text = urllib.parse.urlencode(query)
		url = f"{url}?{query_text}"
	request_headers = {"User-Agent": "homebrew-top-new-script"}
	if headers:
		request_headers.update(headers)
	request = urllib.request.Request(url, headers=request_headers, method="GET")

	# Slight jitter to reduce burst pressure across endpoints.
	time.sleep(random.random())

	with urllib.request.urlopen(request, timeout=30) as response:
		body = response.read().decode("utf-8")
	return json.loads(body)


#============================================
def safe_get_json(url: str, headers: dict[str, str] | None = None, query: dict | None = None) -> tuple[object | None, str | None]:
	"""
	Fetch JSON and return payload or error text.
	"""
	try:
		payload = get_json(url, headers=headers, query=query)
	except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
		return None, str(error)
	return payload, None


#============================================
def read_json_file(path: str) -> object:
	"""
	Read JSON file.
	"""
	with open(path, "r", encoding="utf-8") as handle:
		return json.load(handle)


#============================================
def write_json_file(path: str, payload: object) -> None:
	"""
	Write JSON file.
	"""
	with open(path, "w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, sort_keys=True)


#============================================
def parse_cask_rows_from_container(container: object) -> list[dict]:
	"""
	Parse cask rows from Homebrew cask cache payload container.
	"""
	if isinstance(container, dict):
		payload = container.get("payload")
		if isinstance(payload, list):
			return [row for row in payload if isinstance(row, dict)]
		if isinstance(payload, str):
			decoded = json.loads(payload)
			if isinstance(decoded, list):
				return [row for row in decoded if isinstance(row, dict)]
	if isinstance(container, list):
		return [row for row in container if isinstance(row, dict)]
	raise RuntimeError("Unable to parse cask payload rows.")


#============================================
def load_local_cask_rows(api_dir: str) -> list[dict]:
	"""
	Load cask rows from local Homebrew API cache.
	"""
	cache_path = os.path.join(api_dir, LOCAL_CASK_PAYLOAD_NAME)
	if not os.path.isfile(cache_path):
		raise RuntimeError(f"Missing local cask payload: {cache_path}")
	container = read_json_file(cache_path)
	return parse_cask_rows_from_container(container)


#============================================
def build_cask_meta_map(rows: list[dict]) -> dict[str, dict]:
	"""
	Build token-to-row metadata map.
	"""
	result: dict[str, dict] = {}
	for row in rows:
		token = row.get("token")
		if isinstance(token, str) and token:
			result[token] = row
	return result


#============================================
def read_token_file(path: str) -> list[str]:
	"""
	Read token-per-line file.
	"""
	tokens: list[str] = []
	with open(path, "r", encoding="utf-8") as handle:
		for raw_line in handle:
			line = raw_line.strip()
			if not line:
				continue
			tokens.append(line)
	return tokens


#============================================
def load_current_and_before_tokens(api_dir: str) -> tuple[list[str], list[str], datetime.datetime]:
	"""
	Load current and previous token snapshots and current snapshot timestamp.
	"""
	current_path = os.path.join(api_dir, LOCAL_CASK_NAMES_CURRENT)
	before_path = os.path.join(api_dir, LOCAL_CASK_NAMES_BEFORE)

	if not os.path.isfile(current_path):
		raise RuntimeError(f"Missing local token list: {current_path}")

	current_tokens = read_token_file(current_path)
	before_tokens = read_token_file(before_path) if os.path.isfile(before_path) else []
	mtime = os.path.getmtime(current_path)
	snapshot_dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
	return current_tokens, before_tokens, snapshot_dt


#============================================
def default_state() -> dict:
	"""
	Create default recency state.
	"""
	return {
		"schema_version": STATE_SCHEMA_VERSION,
		"first_seen_utc_by_token": {},
		"first_seen_source_by_token": {},
		"bootstrap_last_run_utc": None,
		"bootstrap_cursor": {},
	}


#============================================
def state_path(work_dir: str) -> str:
	"""
	Return recency state path.
	"""
	return os.path.join(work_dir, STATE_FILE_NAME)


#============================================
def load_state(work_dir: str) -> dict:
	"""
	Load recency state from disk.
	"""
	path = state_path(work_dir)
	if not os.path.isfile(path):
		return default_state()
	try:
		data = read_json_file(path)
	except (OSError, ValueError, json.JSONDecodeError):
		return default_state()
	if not isinstance(data, dict):
		return default_state()

	state = default_state()
	state["schema_version"] = data.get("schema_version", STATE_SCHEMA_VERSION)
	seen = data.get("first_seen_utc_by_token", {})
	sources = data.get("first_seen_source_by_token", {})
	if isinstance(seen, dict):
		state["first_seen_utc_by_token"] = {
			str(key): str(value)
			for key, value in seen.items()
			if isinstance(key, str) and isinstance(value, str)
		}
	if isinstance(sources, dict):
		state["first_seen_source_by_token"] = {
			str(key): str(value)
			for key, value in sources.items()
			if isinstance(key, str) and isinstance(value, str)
		}
	bootstrap_last = data.get("bootstrap_last_run_utc")
	if isinstance(bootstrap_last, str):
		state["bootstrap_last_run_utc"] = bootstrap_last
	cursor = data.get("bootstrap_cursor")
	if isinstance(cursor, dict):
		state["bootstrap_cursor"] = cursor
	return state


#============================================
def save_state(work_dir: str, state: dict) -> None:
	"""
	Save recency state to disk.
	"""
	path = state_path(work_dir)
	write_json_file(path, state)


#============================================
def update_state_with_local_diff(state: dict, current_tokens: list[str], before_tokens: list[str], snapshot_dt: datetime.datetime) -> int:
	"""
	Update recency state for tokens newly observed in local diff.
	"""
	seen = state["first_seen_utc_by_token"]
	sources = state["first_seen_source_by_token"]
	before_set = set(before_tokens)
	added_set = set(current_tokens) - before_set
	added_count = 0
	for token in sorted(added_set):
		if token in seen:
			continue
		seen[token] = to_iso(snapshot_dt)
		sources[token] = "local_snapshot"
		added_count += 1
	return added_count


#============================================
def count_known_tokens(state: dict, current_tokens: list[str]) -> int:
	"""
	Count current tokens that have recency entries.
	"""
	seen = state["first_seen_utc_by_token"]
	return sum(1 for token in current_tokens if token in seen)


#============================================
def github_headers() -> dict[str, str]:
	"""
	Build GitHub API request headers.
	"""
	headers = {"Accept": "application/vnd.github+json"}
	token = os.environ.get("GITHUB_TOKEN")
	if token:
		headers["Authorization"] = f"Bearer {token}"
	return headers


#============================================
def list_cask_commits(page: int, per_page: int = 100) -> list[dict]:
	"""
	List homebrew-cask commits touching Casks path.
	"""
	url = f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits"
	payload = get_json(
		url,
		headers=github_headers(),
		query={"path": "Casks", "per_page": per_page, "page": page},
	)
	if isinstance(payload, list):
		return [entry for entry in payload if isinstance(entry, dict)]
	return []


#============================================
def get_commit_detail(sha: str) -> dict:
	"""
	Get commit detail by SHA.
	"""
	url = f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits/{sha}"
	payload = get_json(url, headers=github_headers())
	if isinstance(payload, dict):
		return payload
	return {}


#============================================
def extract_added_tokens_from_commit(detail: dict) -> list[str]:
	"""
	Extract newly added cask tokens from commit file list.
	"""
	tokens: list[str] = []
	files = detail.get("files")
	if not isinstance(files, list):
		return tokens
	for file_info in files:
		if not isinstance(file_info, dict):
			continue
		status = file_info.get("status")
		filename = file_info.get("filename")
		if status != "added" or not isinstance(filename, str):
			continue
		if not filename.startswith("Casks/") or not filename.endswith(".rb"):
			continue
		base_name = os.path.basename(filename)
		if not base_name.endswith(".rb"):
			continue
		token = base_name[:-3]
		if token:
			tokens.append(token)
	return tokens


#============================================
def local_cask_repo_path() -> str | None:
	"""
	Return local homebrew-cask repo path when available.
	"""
	candidates: list[str] = []
	try:
		brew_path = run_command(["brew", "--repository", "homebrew/cask"])
	except RuntimeError:
		brew_path = ""
	if brew_path:
		candidates.append(brew_path)

	# Allow local sparse clone near this project without requiring a tap.
	cwd = os.getcwd()
	candidates.append(os.path.join(cwd, "homebrew-cask"))
	candidates.append(os.path.join(cwd, "..", "homebrew-cask"))

	seen_paths: set[str] = set()
	for candidate in candidates:
		abs_candidate = os.path.abspath(candidate)
		if abs_candidate in seen_paths:
			continue
		seen_paths.add(abs_candidate)
		if not os.path.isdir(abs_candidate):
			continue
		if not os.path.isdir(os.path.join(abs_candidate, ".git")):
			continue
		return abs_candidate
	return None


#============================================
def run_local_git_bootstrap(state: dict, current_tokens: list[str], newest_pool_size: int) -> dict:
	"""
	Seed first-seen timestamps from local homebrew-cask git history.
	"""
	seen = state["first_seen_utc_by_token"]
	sources = state["first_seen_source_by_token"]
	current_set = set(current_tokens)
	repo_path = local_cask_repo_path()
	if repo_path is None:
		return {
			"used": False,
			"repo_path": None,
			"added_tokens": 0,
			"log_lines": 0,
			"error": "local homebrew/cask git checkout not found",
		}

	try:
		log_output = run_command(
			[
				"git",
				"-C",
				repo_path,
				"log",
				"--diff-filter=A",
				"--name-only",
				"--pretty=format:%cI",
				"--",
				"Casks",
			]
		)
	except RuntimeError as error:
		return {
			"used": True,
			"repo_path": repo_path,
			"added_tokens": 0,
			"log_lines": 0,
			"error": str(error),
		}

	added_tokens = 0
	current_dt: datetime.datetime | None = None
	lines = log_output.splitlines()
	for raw_line in lines:
		line = raw_line.strip()
		if not line:
			continue
		parsed_dt = parse_iso(line)
		if parsed_dt is not None:
			current_dt = parsed_dt
			continue
		if current_dt is None:
			continue
		if not line.startswith("Casks/") or not line.endswith(".rb"):
			continue
		token = os.path.basename(line)[:-3]
		if not token or token not in current_set or token in seen:
			continue
		seen[token] = to_iso(current_dt)
		sources[token] = "local_git_bootstrap"
		added_tokens += 1
		if count_known_tokens(state, current_tokens) >= newest_pool_size:
			break

	return {
		"used": True,
		"repo_path": repo_path,
		"added_tokens": added_tokens,
		"log_lines": len(lines),
		"error": None,
	}


#============================================
def run_bootstrap(
	state: dict,
	current_tokens: list[str],
	newest_pool_size: int,
	max_pages: int,
	max_detail_requests: int,
	warnings: list[str],
) -> dict:
	"""
	Seed first-seen timestamps from local git first, then bounded GitHub fallback.
	"""
	seen = state["first_seen_utc_by_token"]
	sources = state["first_seen_source_by_token"]
	current_set = set(current_tokens)

	local_result = run_local_git_bootstrap(
		state=state,
		current_tokens=current_tokens,
		newest_pool_size=newest_pool_size,
	)
	if local_result["error"] is not None:
		warnings.append(
			f"local git bootstrap unavailable: {local_result['error']}"
		)
	elif local_result["added_tokens"] > 0:
		repo_path = local_result["repo_path"] or "homebrew/cask"
		warnings.append(
			f"local git bootstrap: added {local_result['added_tokens']} "
			f"tokens from {repo_path}"
		)
	if count_known_tokens(state, current_tokens) >= newest_pool_size:
		bootstrap_dt = now_utc()
		state["bootstrap_last_run_utc"] = to_iso(bootstrap_dt)
		state["bootstrap_cursor"] = {
			"source": "local_git",
			"pages_scanned": 0,
			"detail_requests": 0,
			"known_tokens_for_current": count_known_tokens(state, current_tokens),
		}
		return state

	detail_requests = 0
	pages_scanned = 0
	github_error: str | None = None
	for page in range(1, max_pages + 1):
		if count_known_tokens(state, current_tokens) >= newest_pool_size:
			break
		try:
			commits = list_cask_commits(page=page)
		except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
			github_error = str(error)
			break
		if not commits:
			break
		pages_scanned += 1
		for commit in commits:
			if detail_requests >= max_detail_requests:
				break
			sha = commit.get("sha")
			commit_block = commit.get("commit")
			if not isinstance(sha, str) or not isinstance(commit_block, dict):
				continue
			committer = commit_block.get("committer")
			author = commit_block.get("author")
			date_text = None
			if isinstance(committer, dict):
				date_text = committer.get("date")
			if not date_text and isinstance(author, dict):
				date_text = author.get("date")
			if not isinstance(date_text, str):
				continue

			commit_dt = parse_iso(date_text)
			if commit_dt is None:
				continue

			try:
				detail = get_commit_detail(sha)
			except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
				github_error = str(error)
				break
			detail_requests += 1
			added_tokens = extract_added_tokens_from_commit(detail)
			for token in added_tokens:
				if token not in current_set:
					continue
				if token in seen:
					continue
				seen[token] = to_iso(commit_dt)
				sources[token] = "github_bootstrap"
				if count_known_tokens(state, current_tokens) >= newest_pool_size:
					break
		if github_error is not None:
			break
		if detail_requests >= max_detail_requests:
			break

	bootstrap_dt = now_utc()
	state["bootstrap_last_run_utc"] = to_iso(bootstrap_dt)
	state["bootstrap_cursor"] = {
		"source": "github_api",
		"pages_scanned": pages_scanned,
		"detail_requests": detail_requests,
		"known_tokens_for_current": count_known_tokens(state, current_tokens),
	}
	if github_error is not None:
		warnings.append(f"github bootstrap failed: {github_error}")
	return state


#============================================
def parse_count(value: object) -> int:
	"""
	Parse count field into integer.
	"""
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)
	if isinstance(value, str):
		clean = value.replace(",", "").strip()
		if not clean:
			return 0
		if clean.isdigit():
			return int(clean)
	return 0


#============================================
def parse_rank(value: object) -> int | None:
	"""
	Parse rank value into integer when available.
	"""
	if isinstance(value, int):
		return value
	if isinstance(value, str) and value.isdigit():
		return int(value)
	return None


#============================================
def parse_percent(value: object) -> float | None:
	"""
	Parse percent value into float when available.
	"""
	if isinstance(value, (int, float)):
		return float(value)
	if isinstance(value, str):
		clean = value.replace("%", "").replace(",", "").strip()
		if not clean:
			return None
		try:
			return float(clean)
		except ValueError:
			return None
	return None


#============================================
def derive_rank_and_percent(metrics: dict[str, dict], total_count: int) -> dict[str, dict]:
	"""
	Derive rank and percent for metrics with deterministic tie-breaking.
	"""
	ranked_tokens = sorted(
		metrics.keys(),
		key=lambda token: (-metrics[token]["count"], token),
	)
	for index, token in enumerate(ranked_tokens, start=1):
		entry = metrics[token]
		if entry.get("rank") is None:
			entry["rank"] = index
		if entry.get("percent") is None and total_count > 0:
			entry["percent"] = round(entry["count"] * 100.0 / total_count, 2)
	return metrics


#============================================
def parse_analytics_payload(payload: object, window: str, source_kind: str) -> dict[str, dict]:
	"""
	Parse analytics payload into normalized token metrics.
	"""
	metrics: dict[str, dict] = {}
	total_count = 0
	if isinstance(payload, dict):
		total_count = parse_count(payload.get("total_count"))

	if isinstance(payload, dict) and isinstance(payload.get("items"), list):
		for item in payload["items"]:
			if not isinstance(item, dict):
				continue
			token = item.get("cask") or item.get("formula") or item.get("token")
			if not isinstance(token, str) or not token:
				continue
			metrics[token] = {
				"count": parse_count(item.get("count")),
				"rank": parse_rank(item.get("number")),
				"percent": parse_percent(item.get("percent")),
				"window": window,
				"source_kind": source_kind,
			}
		return derive_rank_and_percent(metrics, total_count)

	if isinstance(payload, dict) and isinstance(payload.get("formulae"), dict):
		formulae = payload["formulae"]
		for key, value in formulae.items():
			if not isinstance(key, str):
				continue
			token = key
			count_value: object = 0
			if isinstance(value, list) and value:
				entry = value[0]
				if isinstance(entry, dict):
					entry_token = entry.get("cask") or entry.get("formula")
					if isinstance(entry_token, str) and entry_token:
						token = entry_token
					count_value = entry.get("count")
			elif isinstance(value, dict):
				count_value = value.get("count")
			metrics[token] = {
				"count": parse_count(count_value),
				"rank": None,
				"percent": None,
				"window": window,
				"source_kind": source_kind,
			}
		return derive_rank_and_percent(metrics, total_count)

	if isinstance(payload, list):
		for item in payload:
			if not isinstance(item, dict):
				continue
			token = item.get("cask") or item.get("formula") or item.get("token")
			if not isinstance(token, str) or not token:
				continue
			metrics[token] = {
				"count": parse_count(item.get("count")),
				"rank": parse_rank(item.get("number")),
				"percent": parse_percent(item.get("percent")),
				"window": window,
				"source_kind": source_kind,
			}
		return derive_rank_and_percent(metrics, total_count)

	return metrics


#============================================
def analytics_cache_path(work_dir: str, window: str) -> str:
	"""
	Return analytics cache path for a window.
	"""
	return os.path.join(work_dir, f"analytics_cask_install_{window}.json")


#============================================
def cache_is_fresh(fetched_at: datetime.datetime, ttl_hours: int) -> bool:
	"""
	Check whether cache timestamp is within TTL.
	"""
	age_seconds = (now_utc() - fetched_at).total_seconds()
	return age_seconds <= ttl_hours * 3600


#============================================
def read_cached_analytics(work_dir: str, window: str) -> tuple[dict[str, dict], datetime.datetime, str] | None:
	"""
	Read cached analytics and normalize.
	"""
	path = analytics_cache_path(work_dir, window)
	if not os.path.isfile(path):
		return None
	try:
		payload = read_json_file(path)
	except (OSError, ValueError, json.JSONDecodeError):
		return None

	if isinstance(payload, dict) and "payload" in payload and isinstance(payload.get("fetched_at_utc"), str):
		fetched_at = parse_iso(payload["fetched_at_utc"])
		if fetched_at is None:
			return None
		source_kind = payload.get("source_kind", "cache")
		metrics = parse_analytics_payload(payload["payload"], window, str(source_kind))
		return metrics, fetched_at, str(source_kind)

	mtime = os.path.getmtime(path)
	fetched_at = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
	metrics = parse_analytics_payload(payload, window, "cache_legacy")
	return metrics, fetched_at, "cache_legacy"


#============================================
def write_cached_analytics(work_dir: str, window: str, source_url: str, source_kind: str, payload: object, ttl_hours: int) -> None:
	"""
	Write analytics payload to local cache wrapper.
	"""
	path = analytics_cache_path(work_dir, window)
	wrapper = {
		"fetched_at_utc": to_iso(now_utc()),
		"ttl_hours": ttl_hours,
		"source_url": source_url,
		"source_kind": source_kind,
		"payload": payload,
	}
	try:
		write_json_file(path, wrapper)
	except OSError:
		return


#============================================
def analytics_urls(window: str) -> tuple[str, str]:
	"""
	Return canonical and fallback analytics URLs for a window.
	"""
	canonical = (
		f"{FORMULAE_API_BASE}/analytics/cask-install/homebrew-cask/{window}.json"
	)
	fallback = f"{FORMULAE_API_BASE}/analytics/cask-install/{window}.json"
	return canonical, fallback


#============================================
def load_window_analytics(work_dir: str, window: str, ttl_hours: int, offline: bool, refresh: bool, warnings: list[str]) -> dict[str, dict]:
	"""
	Load analytics metrics for one window with cache and fallback policy.
	"""
	cached = read_cached_analytics(work_dir, window)
	if cached and not refresh:
		cached_metrics, cached_time, _cached_source = cached
		if cache_is_fresh(cached_time, ttl_hours):
			return cached_metrics

	if offline:
		if cached:
			return cached[0]
		warnings.append(f"offline mode: no analytics cache for {window}")
		return {}

	canonical_url, fallback_url = analytics_urls(window)
	canonical_payload, canonical_error = safe_get_json(canonical_url)
	if canonical_payload is not None:
		metrics = parse_analytics_payload(canonical_payload, window, "canonical")
		write_cached_analytics(
			work_dir,
			window,
			canonical_url,
			"canonical",
			canonical_payload,
			ttl_hours,
		)
		return metrics

	fallback_payload, fallback_error = safe_get_json(fallback_url)
	if fallback_payload is not None:
		metrics = parse_analytics_payload(fallback_payload, window, "fallback")
		write_cached_analytics(
			work_dir,
			window,
			fallback_url,
			"fallback",
			fallback_payload,
			ttl_hours,
		)
		return metrics

	if cached:
		warnings.append(
			f"{window} analytics fetch failed; using stale cache "
			f"(canonical={canonical_error}, fallback={fallback_error})"
		)
		return cached[0]

	warnings.append(
		f"{window} analytics unavailable "
		f"(canonical={canonical_error}, fallback={fallback_error})"
	)
	return {}


#============================================
def compute_newest_entries(
	current_tokens: list[str],
	state: dict,
	pool_size: int,
) -> tuple[list[tuple[str, datetime.datetime, str]], int]:
	"""
	Compute newest pool entries from state for current tokens.
	"""
	seen = state["first_seen_utc_by_token"]
	sources = state["first_seen_source_by_token"]
	unknown = 0
	entries: list[tuple[str, datetime.datetime, str]] = []
	for token in current_tokens:
		text = seen.get(token)
		parsed = parse_iso(text) if isinstance(text, str) else None
		if parsed is None:
			unknown += 1
			continue
		source = sources.get(token, "state")
		entries.append((token, parsed, source))
	entries.sort(key=lambda item: (-item[1].timestamp(), item[0]))
	return entries[:pool_size], unknown


#============================================
def display_name_for_meta(token: str, meta: dict) -> str:
	"""
	Get display name from cask metadata.
	"""
	name_field = meta.get("name")
	if isinstance(name_field, list) and name_field:
		return str(name_field[0])
	if isinstance(name_field, str) and name_field:
		return name_field
	return token


#============================================
def metric_for_token(window_metrics: dict[str, dict], token: str) -> dict:
	"""
	Return normalized metric entry for token.
	"""
	value = window_metrics.get(token)
	if isinstance(value, dict):
		return value
	return {"count": 0, "rank": None, "percent": None}


#============================================
def newest_row(
	token: str,
	stamp: datetime.datetime,
	source: str,
	meta_map: dict[str, dict],
	analytics_by_window: dict[str, dict],
	selected_window: str,
) -> dict[str, object]:
	"""
	Build one newest table row payload.
	"""
	meta = meta_map.get(token, {})
	desc = str(meta.get("desc") or "")
	name = display_name_for_meta(token, meta)
	homepage = str(meta.get("homepage") or "")

	m30 = metric_for_token(analytics_by_window["30d"], token)
	m90 = metric_for_token(analytics_by_window["90d"], token)
	m365 = metric_for_token(analytics_by_window["365d"], token)
	mwin = metric_for_token(analytics_by_window[selected_window], token)
	row = {
		"date": stamp.date().isoformat(),
		"token": token,
		"name": name,
		"homepage": homepage,
		"description": desc,
		"installs_30d": int(m30.get("count", 0)),
		"installs_90d": int(m90.get("count", 0)),
		"installs_365d": int(m365.get("count", 0)),
		"source": source,
	}
	return row


#============================================
def popular_row(
	token: str,
	meta_map: dict[str, dict],
	window_metrics: dict[str, dict],
	selected_window: str,
) -> dict[str, object]:
	"""
	Build one popular table row payload.
	"""
	meta = meta_map.get(token, {})
	desc = str(meta.get("desc") or "")
	name = display_name_for_meta(token, meta)
	homepage = str(meta.get("homepage") or "")
	metric = metric_for_token(window_metrics, token)
	row = {
		"token": token,
		"name": name,
		"homepage": homepage,
		"description": desc,
		"count": int(metric.get("count", 0)),
		"window": selected_window,
	}
	return row


#============================================
def build_newest_rows(
	entries: list[tuple[str, datetime.datetime, str]],
	meta_map: dict[str, dict],
	analytics_by_window: dict[str, dict],
	selected_window: str,
	print_count: int,
) -> list[dict[str, object]]:
	"""
	Build newest table rows.
	"""
	rows: list[dict[str, object]] = []
	limit = min(print_count, len(entries))
	for token, stamp, source in entries[:limit]:
		row = newest_row(
			token=token,
			stamp=stamp,
			source=source,
			meta_map=meta_map,
			analytics_by_window=analytics_by_window,
			selected_window=selected_window,
		)
		rows.append(row)
	return rows


#============================================
def build_popular_rows(
	entries: list[tuple[str, datetime.datetime, str]],
	meta_map: dict[str, dict],
	window_metrics: dict[str, dict],
	selected_window: str,
	print_count: int,
) -> list[dict[str, object]]:
	"""
	Build popular table rows.
	"""
	tokens = [token for token, _stamp, _source in entries]
	ranked = sorted(
		tokens,
		key=lambda token: (-metric_for_token(window_metrics, token)["count"], token),
	)
	rows: list[dict[str, object]] = []
	for token in ranked[:print_count]:
		rows.append(
			popular_row(
				token=token,
				meta_map=meta_map,
				window_metrics=window_metrics,
				selected_window=selected_window,
			)
		)
	return rows


#============================================
def render_name_cell(name: str, homepage: str) -> str:
	"""
	Render a name table cell, linking to homepage when available.
	"""
	escaped_name = html.escape(name)
	if homepage:
		escaped_url = html.escape(homepage, quote=True)
		cell = (
			f"<td data-sort='{escaped_name}'>"
			f"<a href='{escaped_url}' target='_blank' rel='noopener'>"
			f"{escaped_name}</a></td>"
		)
		return cell
	cell = f"<td data-sort='{escaped_name}'>{escaped_name}</td>"
	return cell


#============================================
def render_newest_table_rows(rows: list[dict[str, object]]) -> str:
	"""
	Render newest HTML table rows.
	"""
	parts: list[str] = []
	for row in rows:
		# render name as a clickable link when homepage is available
		name_cell = render_name_cell(str(row["name"]), str(row.get("homepage", "")))
		parts.append(
			"<tr>"
			f"<td data-sort='{row['date']}'>{html.escape(str(row['date']))}</td>"
			f"<td data-sort='{row['token']}'>{html.escape(str(row['token']))}</td>"
			f"{name_cell}"
			f"<td data-sort='{row['description']}'>{html.escape(str(row['description']))}</td>"
			f"<td data-sort='{row['installs_30d']}'>{row['installs_30d']}</td>"
			f"<td data-sort='{row['installs_90d']}'>{row['installs_90d']}</td>"
			f"<td data-sort='{row['installs_365d']}'>{row['installs_365d']}</td>"
			f"<td data-sort='{row['source']}'>{html.escape(str(row['source']))}</td>"
			"</tr>"
		)
	return "\n".join(parts)


#============================================
def render_popular_table_rows(rows: list[dict[str, object]]) -> str:
	"""
	Render popular HTML table rows.
	"""
	parts: list[str] = []
	for row in rows:
		# render name as a clickable link when homepage is available
		name_cell = render_name_cell(str(row["name"]), str(row.get("homepage", "")))
		parts.append(
			"<tr>"
			f"<td data-sort='{row['count']}'>{row['count']}</td>"
			f"<td data-sort='{row['token']}'>{html.escape(str(row['token']))}</td>"
			f"{name_cell}"
			f"<td data-sort='{row['description']}'>{html.escape(str(row['description']))}</td>"
			"</tr>"
		)
	return "\n".join(parts)


#============================================
def render_warnings(warnings: list[str]) -> str:
	"""
	Render warnings block.
	"""
	if not warnings:
		return "<p>None.</p>"
	items = []
	for warning in warnings:
		items.append(f"<li>{html.escape(warning)}</li>")
	return "<ul>" + "".join(items) + "</ul>"


#============================================
def render_html_report(
	newest_rows: list[dict[str, object]],
	popular_rows: list[dict[str, object]],
	selected_window: str,
	warnings: list[str],
	newest_pool_size: int,
) -> str:
	"""
	Render standalone HTML report with sortable tables.
	"""
	timestamp = to_iso(now_utc())
	newest_rows_html = render_newest_table_rows(newest_rows)
	popular_rows_html = render_popular_table_rows(popular_rows)
	warnings_html = render_warnings(warnings)
	html_text = (
		"<!doctype html>\n"
		"<html lang='en'>\n"
		"<head>\n"
		"<meta charset='utf-8'>\n"
		"<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
		"<title>Homebrew Top New Report</title>\n"
		"<style>\n"
		":root { --bg:#f5f2ea; --panel:#fffaf0; --ink:#1f2a1f; --accent:#1f6f5f; --line:#d6cfbe; }\n"
		"body { margin:0; padding:24px; background:linear-gradient(145deg,#efe9dc,#f9f6ef); "
		"color:var(--ink); font-family: Menlo, Monaco, Consolas, monospace; }\n"
		"h1,h2 { margin:0 0 12px 0; }\n"
		".meta { margin:0 0 20px 0; }\n"
		".panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:18px; }\n"
		"table { width:100%; border-collapse:collapse; table-layout:fixed; }\n"
		"th,td { border:1px solid var(--line); padding:8px; vertical-align:top; word-wrap:break-word; }\n"
		"th { background:#e8e2d3; cursor:pointer; position:sticky; top:0; z-index:1; }\n"
		"th:hover { background:#ddd5c2; }\n"
		"a { color:var(--accent); text-decoration:none; }\n"
		"a:hover { text-decoration:underline; }\n"
		".small { font-size:12px; color:#4d5a4d; }\n"
		".hint { color:var(--accent); margin-bottom:8px; }\n"
		"</style>\n"
		"</head>\n"
		"<body>\n"
		"<h1>Homebrew Newest Casks Report</h1>\n"
		f"<p class='meta'>Generated: {html.escape(timestamp)} | "
		f"Newest pool: {newest_pool_size} | Selected window: {html.escape(selected_window)}</p>\n"
		"<div class='panel'>\n"
		"<h2>Warnings and Data Notes</h2>\n"
		f"{warnings_html}\n"
		"</div>\n"
		"<div class='panel'>\n"
		f"<h2>Newest {len(newest_rows)} Casks</h2>\n"
		"<p class='hint'>Click column headers to sort.</p>\n"
		"<table data-sort-dir='desc'>\n"
		"<colgroup>"
		"<col style='width:8%'>"
		"<col style='width:12%'>"
		"<col style='width:12%'>"
		"<col style='width:32%'>"
		"<col style='width:9%'>"
		"<col style='width:9%'>"
		"<col style='width:9%'>"
		"<col style='width:9%'>"
		"</colgroup>\n"
		"<thead><tr>"
		"<th>Date</th><th>Token</th><th>Name</th><th>Description</th>"
		"<th>Installs 30d</th><th>Installs 90d</th><th>Installs 365d</th>"
		"<th>Recency Source</th>"
		"</tr></thead>\n"
		f"<tbody>{newest_rows_html}</tbody>\n"
		"</table>\n"
		"</div>\n"
		"<div class='panel'>\n"
		f"<h2>Top {len(popular_rows)} Popular Among Newest {newest_pool_size}</h2>\n"
		"<p class='hint'>Click column headers to sort.</p>\n"
		"<table data-sort-dir='desc'>\n"
		"<colgroup>"
		"<col style='width:10%'>"
		"<col style='width:15%'>"
		"<col style='width:15%'>"
		"<col style='width:60%'>"
		"</colgroup>\n"
		"<thead><tr>"
		f"<th>Installs {html.escape(selected_window)}</th>"
		"<th>Token</th><th>Name</th><th>Description</th>"
		"</tr></thead>\n"
		f"<tbody>{popular_rows_html}</tbody>\n"
		"</table>\n"
		"</div>\n"
		"<p class='small'>Static report generated by homebrew_top_new.py</p>\n"
		"<script>\n"
		"function sortTable(table, col, direction) {\n"
		"  const tbody = table.tBodies[0];\n"
		"  const rows = Array.from(tbody.rows);\n"
		"  const dir = direction === 'asc' ? 1 : -1;\n"
		"  rows.sort((a, b) => {\n"
		"    const av = a.cells[col].dataset.sort || a.cells[col].textContent.trim();\n"
		"    const bv = b.cells[col].dataset.sort || b.cells[col].textContent.trim();\n"
		"    const an = Number(av);\n"
		"    const bn = Number(bv);\n"
		"    if (!Number.isNaN(an) && !Number.isNaN(bn)) {\n"
		"      return (an - bn) * dir;\n"
		"    }\n"
		"    return av.localeCompare(bv) * dir;\n"
		"  });\n"
		"  rows.forEach((row) => tbody.appendChild(row));\n"
		"}\n"
		"document.querySelectorAll('table').forEach((table) => {\n"
		"  const headers = Array.from(table.querySelectorAll('th'));\n"
		"  headers.forEach((th, idx) => {\n"
		"    th.addEventListener('click', () => {\n"
		"      const current = th.dataset.dir || table.dataset.sortDir || 'desc';\n"
		"      const next = current === 'asc' ? 'desc' : 'asc';\n"
		"      headers.forEach((h) => delete h.dataset.dir);\n"
		"      th.dataset.dir = next;\n"
		"      sortTable(table, idx, next);\n"
		"    });\n"
		"  });\n"
		"});\n"
		"</script>\n"
		"</body>\n"
		"</html>\n"
	)
	return html_text


#============================================
def write_html_report(path: str, html_text: str) -> None:
	"""
	Write HTML report file.
	"""
	with open(path, "w", encoding="utf-8") as handle:
		handle.write(html_text)


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse CLI arguments.
	"""
	parser = argparse.ArgumentParser(
		description=(
			"Show newest Homebrew casks plus popularity among them (local-first)."
		),
	)
	parser.add_argument(
		"--analytics-window",
		choices=WINDOWS,
		default=DEFAULT_ANALYTICS_WINDOW,
		help="Analytics window for popularity ranking.",
	)
	parser.add_argument(
		"--analytics-cache-ttl-hours",
		type=int,
		default=DEFAULT_ANALYTICS_TTL_HOURS,
		help="Hours before analytics cache is considered stale.",
	)
	parser.add_argument(
		"--refresh-analytics",
		action="store_true",
		help="Force refresh analytics, bypassing TTL freshness check.",
	)
	parser.add_argument(
		"--offline",
		action="store_true",
		help="Do not fetch network resources; use only local cache/state.",
	)
	parser.add_argument(
		"--refresh-bootstrap",
		action="store_true",
		help="Force recency bootstrap pass (local git first, then GitHub fallback).",
	)
	parser.add_argument(
		"--bootstrap-max-pages",
		type=int,
		default=DEFAULT_BOOTSTRAP_MAX_PAGES,
		help="Max GitHub commit-list pages to scan during bootstrap.",
	)
	return parser.parse_args()


#============================================
def main() -> int:
	"""
	Run report generation.
	"""
	args = parse_args()
	warnings: list[str] = []

	api_dir = get_api_cache_dir()
	work_dir = get_work_dir(api_dir, warnings)
	rows = load_local_cask_rows(api_dir)
	meta_map = build_cask_meta_map(rows)

	current_tokens, before_tokens, snapshot_dt = load_current_and_before_tokens(api_dir)
	state = load_state(work_dir)
	update_state_with_local_diff(state, current_tokens, before_tokens, snapshot_dt)

	known_count = count_known_tokens(state, current_tokens)
	needs_bootstrap = args.refresh_bootstrap or known_count < DEFAULT_NEWEST_POOL_SIZE
	if needs_bootstrap:
		if args.offline:
			warnings.append("offline mode: skipped recency bootstrap")
		else:
			run_bootstrap(
				state=state,
				current_tokens=current_tokens,
				newest_pool_size=DEFAULT_NEWEST_POOL_SIZE,
				max_pages=max(args.bootstrap_max_pages, 1),
				max_detail_requests=DEFAULT_BOOTSTRAP_MAX_DETAIL_REQUESTS,
				warnings=warnings,
			)
	save_state(work_dir, state)

	newest_entries, unknown_count = compute_newest_entries(
		current_tokens=current_tokens,
		state=state,
		pool_size=DEFAULT_NEWEST_POOL_SIZE,
	)
	if not newest_entries:
		print("No current casks found from local token list.", file=sys.stderr)
		return 1
	if unknown_count > 0:
		warnings.append(
			f"{unknown_count} current tokens do not have first-seen dates yet"
		)

	analytics_by_window: dict[str, dict] = {}
	for window in WINDOWS:
		analytics_by_window[window] = load_window_analytics(
			work_dir=work_dir,
			window=window,
			ttl_hours=max(args.analytics_cache_ttl_hours, 1),
			offline=args.offline,
			refresh=args.refresh_analytics,
			warnings=warnings,
		)

	newest_rows = build_newest_rows(
		entries=newest_entries,
		meta_map=meta_map,
		analytics_by_window=analytics_by_window,
		selected_window=args.analytics_window,
		print_count=DEFAULT_NEWEST_PRINT_COUNT,
	)
	popular_rows = build_popular_rows(
		entries=newest_entries,
		meta_map=meta_map,
		window_metrics=analytics_by_window[args.analytics_window],
		selected_window=args.analytics_window,
		print_count=DEFAULT_POPULAR_PRINT_COUNT,
	)
	report_html = render_html_report(
		newest_rows=newest_rows,
		popular_rows=popular_rows,
		selected_window=args.analytics_window,
		warnings=warnings,
		newest_pool_size=DEFAULT_NEWEST_POOL_SIZE,
	)
	report_path = os.path.abspath(DEFAULT_REPORT_FILE)
	write_html_report(report_path, report_html)
	print(f"Wrote report: {report_path}")
	print(
		f"Newest rows: {len(newest_rows)} | Popular rows: {len(popular_rows)} | "
		f"Warnings: {len(warnings)}"
	)

	if warnings:
		print("See warnings section in the HTML report.", file=sys.stderr)
	return 0


#============================================
if __name__ == "__main__":
	raise SystemExit(main())
