"""PyInstaller entry point; absolute import preserves the package context."""
from backend.imaging_desktop.__main__ import main

if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        # A --windowed bootloader otherwise opens a modal traceback and blocks
        # unattended CI. This report is restricted to generated-data self-tests.
        import json
        from pathlib import Path
        import sys
        import traceback
        if "--self-test-core" not in sys.argv:
            raise
        index = sys.argv.index("--self-test-core")
        Path(sys.argv[index+1]).write_text(json.dumps({"core_self_test": "failed", "synthetic_only": True,
                                                     "traceback": traceback.format_exc()}, indent=2), encoding="utf-8")
        result = 1
    raise SystemExit(result)
