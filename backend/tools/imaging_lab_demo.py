"""Exercise only the fixed loopback synthetic lab; never accepts a URL or patient file."""

import json

from backend.app.imaging_intelligence.synthetic_lab import SyntheticDicomWebLab


def main():
    lab = SyntheticDicomWebLab()
    try:
        print(json.dumps(lab.run(), sort_keys=True, indent=2))
    finally:
        lab.close()


if __name__ == "__main__":
    main()
