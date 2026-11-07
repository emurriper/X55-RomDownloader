"""Extracción de una sola ROM de un 7z con la herramienta nativa de ROCKNIX."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import zlib

from download_core import ExtractZip, component, _remember_installation


class Extract7z(ExtractZip):
    def _metadata(self, executable):
        result = subprocess.run([executable, 'l', '-t7z', '-slt', '-ba', '-sccUTF-8', '-p-', '--', str(self.archive)],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError('No se pudo leer el 7z; puede estar dañado o cifrado. Se conserva el archivo.')
        blocks = result.stdout.decode('utf-8', 'strict').replace('\r\n', '\n').split('\n\n')
        files = []
        for block in blocks:
            fields = dict(line.split(' = ', 1) for line in block.splitlines() if ' = ' in line)
            if 'Path' not in fields:
                continue
            parts = fields['Path'].split('/')
            for part in parts:
                component(part)
            attributes = fields.get('Attributes', '')
            if ('Symbolic Link' in fields or 'Hard Link' in fields
                    or any(value.startswith('l') for value in attributes.split())):
                raise ValueError('El 7z contiene un enlace simbólico. Se conserva el comprimido.')
            if fields.get('Folder') == '+' or attributes.startswith('D'):
                continue
            if fields.get('Encrypted') == '+':
                raise ValueError('No se admiten archivos 7z cifrados.')
            files.append(SimpleNamespace(filename=parts[-1], file_size=int(fields['Size']), CRC=int(fields['CRC'], 16)))
        if len(files) != 1 or Path(files[0].filename).suffix.lower() not in self.EXTENSIONS:
            raise ValueError('Extracción automática: se necesita una sola ROM compatible. Se conserva el 7z para extracción manual.')
        return files[0]

    def _run(self):
        temporary = reserved = process = None
        finished = threading.Event()
        try:
            executable = shutil.which('7za') or shutil.which('7zz') or shutil.which('7z')
            if not executable:
                raise RuntimeError('No se encuentra una herramienta 7z en la consola.')
            self.archive = self.archive.resolve()
            original = self.identity(self.archive)
            item = self._metadata(executable)
            root = self.archive.parent
            target = root / item.filename
            if os.path.lexists(target):
                self._verify_existing(target, item, original)
                return
            if shutil.disk_usage(root).free < item.file_size + 64 * 1024 * 1024:
                raise OSError('No hay espacio suficiente para extraer la ROM.')
            self.update(total=item.file_size)
            copied, crc = 0, 0
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen([executable, 'x', '-t7z', '-so', '-bd', '-bb0', '-p-', '--', str(self.archive)],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors)
                def watch():
                    while not finished.wait(0.1):
                        if self.cancel.is_set() and process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                process.kill()
                            return
                watcher = threading.Thread(target=watch, daemon=True)
                watcher.start()
                try:
                    with tempfile.NamedTemporaryFile(dir=root, prefix='.x55-extract-', suffix='.part', delete=False) as output:
                        temporary = Path(output.name)
                        while not self.cancel.is_set():
                            chunk = process.stdout.read(1024 * 1024)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if copied > item.file_size:
                                raise ValueError('El 7z excede el tamaño anunciado.')
                            crc = zlib.crc32(chunk, crc)
                            output.write(chunk)
                            self.update(downloaded=copied)
                        if self.cancel.is_set():
                            self.update(status='cancelled')
                            return
                        output.flush()
                        os.fsync(output.fileno())
                    code = process.wait(timeout=10)
                    if code or copied != item.file_size or crc != item.CRC:
                        raise ValueError('No se pudo verificar la integridad del 7z. Se conserva el comprimido.')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    process.stdout.close()
                    finished.set()
                    watcher.join(timeout=3)
            if self.identity(self.archive) != original:
                raise ValueError('El comprimido cambió durante la extracción.')
            if self.cancel.is_set():
                self.update(status='cancelled')
                return
            with target.open('xb'):
                reserved = target
            os.replace(temporary, target)
            temporary = reserved = None
            self.output = target
            self.verified_archive = original
            self.verified_output = self.identity(target)
            _remember_installation(self.archive, target)
            self.update(status='done')
        except Exception as error:
            self.update(status='cancelled' if self.cancel.is_set() else 'error', error=str(error))
        finally:
            finished.set()
            for path in (temporary, reserved):
                if path is not None:
                    path.unlink(missing_ok=True)
