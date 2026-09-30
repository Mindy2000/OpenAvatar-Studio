"""Reject release labels that disagree with the version embedded in the application."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openavatar import __version__


def validate_version(label: str) -> None:
    if label != 'preview' and label.removeprefix('v') != __version__:
        raise ValueError(f'Release label {label!r} does not match application version {__version__!r}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    validate_version(parser.parse_args().version)
