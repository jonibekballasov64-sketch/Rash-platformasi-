"""Yordamchi: 6 xonali (harf+raqam aralash) noyob test kodi generatsiya qilish."""
from __future__ import annotations

import random
import string

_ALPHABET = string.ascii_uppercase + string.digits


def generate_test_code() -> str:
    return "".join(random.choices(_ALPHABET, k=6))
