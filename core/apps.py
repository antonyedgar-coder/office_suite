import importlib.util
import os
import traceback
from pathlib import Path

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        if os.environ.get("RUN_MAIN") != "true":
            return
        base = Path(__file__).resolve().parent.parent
        trigger = base / "docs" / ".build_docx_trigger"
        if not trigger.exists():
            return
        log = base / "docs" / "build_docx_log.txt"
        try:
            script = base / "docs" / "build_word_manual.py"
            spec = importlib.util.spec_from_file_location("build_word_manual", script)
            if not spec or not spec.loader:
                raise RuntimeError("Could not load build_word_manual.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.build()
            log.write_text("OK\n", encoding="utf-8")
        except Exception:
            log.write_text(traceback.format_exc(), encoding="utf-8")
