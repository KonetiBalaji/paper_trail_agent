"""Keep Vercel's flat manifest aligned with the tested portable lock pins."""
from pathlib import Path
from packaging.requirements import Requirement

ROOT=Path(__file__).resolve().parents[1]


def main():
    def lines(name):return [line.strip() for line in (ROOT/name).read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
    actual=lines('requirements.txt');locked=lines('requirements-lock.txt')
    if any(line.startswith('-') for line in actual):raise ValueError('Vercel manifest must be flat, without pip includes/options')
    expected=[line for line in locked if not line.lower().startswith('pywin32==')]
    if actual!=expected:raise ValueError('Deployment manifest differs from tested portable lock pins')
    for line in actual:
        requirement=Requirement(line)
        if not str(requirement.specifier).startswith('=='):raise ValueError('Deployment versions must be pinned')
    print('Flat deployment manifest matches tested portable dependency pins.')


if __name__=='__main__':main()
