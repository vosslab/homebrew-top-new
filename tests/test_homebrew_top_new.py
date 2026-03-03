import datetime
import json

import homebrew_top_new


#============================================
def test_parse_cask_rows_from_container_string_payload() -> None:
	"""Parse rows from cask payload encoded as JSON string."""
	payload = [
		{"token": "alpha", "desc": "alpha app"},
		{"token": "beta", "desc": "beta app"},
	]
	container = {"payload": json.dumps(payload)}
	rows = homebrew_top_new.parse_cask_rows_from_container(container)
	assert len(rows) == 2
	assert rows[0]["token"] == "alpha"
	assert rows[1]["token"] == "beta"


#============================================
def test_parse_analytics_payload_items_shape() -> None:
	"""Parse analytics payload with items list shape."""
	payload = {
		"total_count": 1000,
		"items": [
			{"number": 1, "cask": "alpha", "count": "300", "percent": "30.0"},
			{"number": 2, "cask": "beta", "count": "100", "percent": "10.0"},
		],
	}
	metrics = homebrew_top_new.parse_analytics_payload(payload, "30d", "fallback")
	assert metrics["alpha"]["count"] == 300
	assert metrics["alpha"]["rank"] == 1
	assert metrics["alpha"]["percent"] == 30.0
	assert metrics["beta"]["count"] == 100
	assert metrics["beta"]["rank"] == 2


#============================================
def test_parse_analytics_payload_formulae_shape_derives_rank_percent() -> None:
	"""Parse map shape and derive rank/percent when absent."""
	payload = {
		"total_count": "1000",
		"formulae": {
			"alpha": [{"cask": "alpha", "count": "250"}],
			"beta": [{"cask": "beta", "count": "100"}],
		},
	}
	metrics = homebrew_top_new.parse_analytics_payload(payload, "30d", "canonical")
	assert metrics["alpha"]["count"] == 250
	assert metrics["beta"]["count"] == 100
	assert metrics["alpha"]["rank"] == 1
	assert metrics["beta"]["rank"] == 2
	assert metrics["alpha"]["percent"] == 25.0
	assert metrics["beta"]["percent"] == 10.0


#============================================
def test_update_state_with_local_diff() -> None:
	"""Insert first-seen dates for local diff additions."""
	state = homebrew_top_new.default_state()
	current = ["alpha", "beta", "gamma"]
	before = ["alpha"]
	snapshot = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
	added_count = homebrew_top_new.update_state_with_local_diff(
		state,
		current,
		before,
		snapshot,
	)
	assert added_count == 2
	seen = state["first_seen_utc_by_token"]
	sources = state["first_seen_source_by_token"]
	assert "beta" in seen
	assert "gamma" in seen
	assert sources["beta"] == "local_snapshot"
	assert sources["gamma"] == "local_snapshot"


#============================================
def test_compute_newest_entries_deterministic_tie_break() -> None:
	"""Sort by first-seen desc and token asc for ties."""
	state = homebrew_top_new.default_state()
	iso = "2026-03-01T00:00:00+00:00"
	state["first_seen_utc_by_token"] = {
		"zeta": iso,
		"alpha": iso,
		"beta": "2026-02-01T00:00:00+00:00",
	}
	state["first_seen_source_by_token"] = {
		"zeta": "github_bootstrap",
		"alpha": "github_bootstrap",
		"beta": "local_snapshot",
	}
	entries, unknown_count = homebrew_top_new.compute_newest_entries(
		["zeta", "alpha", "beta"],
		state,
		3,
	)
	assert unknown_count == 0
	assert entries[0][0] == "alpha"
	assert entries[1][0] == "zeta"
	assert entries[2][0] == "beta"


#============================================
def test_compute_newest_entries_excludes_unknown_tokens() -> None:
	"""Never include unknown tokens in newest output."""
	state = homebrew_top_new.default_state()
	state["first_seen_utc_by_token"] = {
		"alpha": "2026-03-01T00:00:00+00:00",
	}
	state["first_seen_source_by_token"] = {
		"alpha": "local_snapshot",
	}
	entries, unknown_count = homebrew_top_new.compute_newest_entries(
		["alpha", "adobe-acrobat-reader"],
		state,
		10,
	)
	assert len(entries) == 1
	assert entries[0][0] == "alpha"
	assert unknown_count == 1


#============================================
def test_cache_is_fresh_recent_timestamp() -> None:
	"""Validate cache freshness window check."""
	fetched_at = homebrew_top_new.now_utc() - datetime.timedelta(hours=1)
	assert homebrew_top_new.cache_is_fresh(fetched_at, 24)


#============================================
def test_run_local_git_bootstrap_parses_git_log(monkeypatch) -> None:
	"""Seed first-seen values from local git log output."""
	state = homebrew_top_new.default_state()
	current_tokens = ["alpha", "beta", "gamma"]
	log_text = (
		"2026-02-20T12:00:00+00:00\n"
		"Casks/a/alpha.rb\n"
		"\n"
		"2026-02-10T09:30:00+00:00\n"
		"Casks/b/beta.rb\n"
		"Casks/z/zeta.rb\n"
	)

	def fake_local_path() -> str | None:
		return "/tmp/homebrew-cask"

	def fake_run_command(args: list[str]) -> str:
		assert args[0] == "git"
		return log_text

	monkeypatch.setattr(homebrew_top_new, "local_cask_repo_path", fake_local_path)
	monkeypatch.setattr(homebrew_top_new, "run_command", fake_run_command)

	result = homebrew_top_new.run_local_git_bootstrap(
		state=state,
		current_tokens=current_tokens,
		newest_pool_size=3,
	)
	seen = state["first_seen_utc_by_token"]
	sources = state["first_seen_source_by_token"]
	assert result["used"] is True
	assert result["added_tokens"] == 2
	assert seen["alpha"] == "2026-02-20T12:00:00+00:00"
	assert seen["beta"] == "2026-02-10T09:30:00+00:00"
	assert sources["alpha"] == "local_git_bootstrap"
	assert sources["beta"] == "local_git_bootstrap"


#============================================
def test_local_cask_repo_path_prefers_nearby_clone(monkeypatch, tmp_path) -> None:
	"""Find local homebrew-cask clone in current workspace neighborhood."""
	work = tmp_path / "project"
	clone = tmp_path / "homebrew-cask"
	work.mkdir()
	clone.mkdir()
	(clone / ".git").mkdir()

	def fake_run_command(args: list[str]) -> str:
		assert args[:3] == ["brew", "--repository", "homebrew/cask"]
		return str(tmp_path / "missing-tap")

	monkeypatch.setattr(homebrew_top_new, "run_command", fake_run_command)
	monkeypatch.setattr(homebrew_top_new.os, "getcwd", lambda: str(work))
	found = homebrew_top_new.local_cask_repo_path()
	assert found == str(clone)


#============================================
def test_run_bootstrap_github_error_adds_warning(monkeypatch) -> None:
	"""Handle GitHub failures with warning instead of crash."""
	state = homebrew_top_new.default_state()
	warnings: list[str] = []

	def fake_local_bootstrap(state: dict, current_tokens: list[str], newest_pool_size: int) -> dict:
		return {
			"used": False,
			"repo_path": None,
			"added_tokens": 0,
			"log_lines": 0,
			"error": "not available",
		}

	def fake_list_cask_commits(page: int, per_page: int = 100) -> list[dict]:
		raise RuntimeError("HTTP Error 403: rate limit exceeded")

	monkeypatch.setattr(homebrew_top_new, "run_local_git_bootstrap", fake_local_bootstrap)
	monkeypatch.setattr(homebrew_top_new, "list_cask_commits", fake_list_cask_commits)

	homebrew_top_new.run_bootstrap(
		state=state,
		current_tokens=["alpha"],
		newest_pool_size=1,
		max_pages=1,
		max_detail_requests=1,
		warnings=warnings,
	)
	assert any("github bootstrap failed" in item for item in warnings)


#============================================
def test_render_html_report_contains_sortable_tables_and_escape() -> None:
	"""Render report with tables and escaped description content."""
	newest_rows = [
		{
			"date": "2026-03-01",
			"token": "alpha",
			"name": "Alpha",
			"description": "A <tag> app",
			"installs_30d": 5,
			"installs_90d": 9,
			"installs_365d": 12,
			"rank": 1,
			"rank_display": "1",
			"percent": 12.5,
			"percent_display": "12.50",
			"source": "local_snapshot",
		}
	]
	popular_rows = [
		{
			"token": "alpha",
			"name": "Alpha",
			"description": "A <tag> app",
			"count": 5,
			"rank": 1,
			"rank_display": "1",
			"percent": 12.5,
			"percent_display": "12.50",
			"window": "30d",
		}
	]
	report = homebrew_top_new.render_html_report(
		newest_rows=newest_rows,
		popular_rows=popular_rows,
		selected_window="30d",
		warnings=["warning <x>"],
		newest_pool_size=250,
	)
	assert "<table" in report
	assert "Click column headers to sort." in report
	assert "A &lt;tag&gt; app" in report
	assert "warning &lt;x&gt;" in report
