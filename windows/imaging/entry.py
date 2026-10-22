"""PyInstaller entry point; absolute import preserves the package context."""
from backend.imaging_desktop.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
