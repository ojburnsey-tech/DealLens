"""Execute notebooks; --in-process supports hosts that prohibit kernel sockets."""
import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--in-process', action='store_true', help='Execute cells in isolated IPython namespaces; no kernel protocol check')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
paths = sorted((root / 'notebooks').glob('*.ipynb'))
if len(paths) != 6:
    raise RuntimeError('Expected six DealLens notebooks')
for path in paths:
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    if args.in_process:
        from IPython.core.interactiveshell import InteractiveShell
        shell = InteractiveShell(user_ns={})
        for cell in notebook.cells:
            if cell.cell_type == 'code':
                result = shell.run_cell(cell.source)
                result.raise_error()
    else:
        NotebookClient(notebook, timeout=120, kernel_name='python3',
                       resources={'metadata': {'path': str(root)}}).execute()
    print(f'PASS {path.name} ({"in-process cells" if args.in_process else "Jupyter kernel"})', flush=True)
