"""SAMPLE_MODE: a clean clone runs with Maya's local files and the recorded answers, no Zetaris, no Nightshift and no
keys, and calls no AI provider."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ("import config; print(config.SAMPLE_MODE, config.DATA_BACKEND, config.ANSWER_MODE, config.ai_configured())")


def _config_with(env_extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NVIDIA_", "METERLESS_", "SAMPLE_MODE",
                                                                     "DATA_BACKEND", "ANSWER_MODE", "AI_PROVIDER"))}
    env.update(env_extra, LOCALAPPDATA=str(ROOT / "tests" / "fixtures" / "no-runtime-here"))
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def test_sample_mode_forces_local_files_and_recorded_answers_and_no_ai():
    assert _config_with({"SAMPLE_MODE": "true", "DATA_BACKEND": "zetaris", "ANSWER_MODE": "live",
                         "NVIDIA_API_KEY": "x", "METERLESS_RUNTIME_TOKEN": "y"}) == ["True", "local", "replay", "False"]


def test_full_mode_keeps_the_settings_underneath():
    assert _config_with({"SAMPLE_MODE": "false", "DATA_BACKEND": "zetaris", "ANSWER_MODE": "live",
                         "METERLESS_RUNTIME_TOKEN": "y"}) == ["False", "zetaris", "live", "True"]
