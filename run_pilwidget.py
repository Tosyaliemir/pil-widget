from pathlib import Path
import sys

# PYTHONSAFEPATH=1 ya da farklı çalışma klasörü (System32) durumunda da paketi bul.
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pilwidget.app import main

if __name__ == "__main__":
    main()
