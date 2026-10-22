"""Retain the notices shipped in the actual Python distributions being bundled."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
packages = ("PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6", "numpy", "pydicom", "vtk", "pyinstaller")
for name in packages:
    package = distribution(name)
    target = destination/name
    target.mkdir(exist_ok=True)
    notices = []
    for entry in package.files or ():
        if any(word in str(entry).lower() for word in ("license", "copying", "copyright")):
            source = Path(package.locate_file(entry))
            if source.is_file() and source.suffix.lower() not in (".py", ".pyc", ".pyd", ".dll"):
                file = target/str(entry).replace("/", "__").replace("\\", "__")
                shutil.copyfile(source, file)
                notices.append(file.name)
    (target/"distribution.txt").write_text(
        f"{package.metadata['Name']} {package.version}\n"+str(package.metadata)+"\nRetained notices:\n"+"\n".join(notices), encoding="utf-8")
