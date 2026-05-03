import os
import sys
import base64
import zipfile
import random
import zlib
import marshal
import py_compile
import tempfile
import shutil
import hashlib
import string
import subprocess
import logging
import re
import struct
import platform
import types
import dis
import opcode
from binascii import hexlify, unhexlify
from io import BytesIO
from pathlib import Path
ENCODER_PYTHON_VERSION = sys.version_info[:2]

def check_python_version_compatibility(min_version=(3, 8)):
    if sys.version_info < min_version:
        print(f'\x1b[31m[!] Python {min_version[0]}.{min_version[1]}+ gerekli! Mevcut: {sys.version_info.major}.{sys.version_info.minor}\x1b[0m')
        sys.exit(1)

def warn_version_mismatch(encoded_on_version):
    cur = sys.version_info[:2]
    enc = encoded_on_version
    if cur != enc:
        print(f'\x1b[93m[!] UYARI: Bu dosya Python {enc[0]}.{enc[1]} ile şifrelendi.')
        print(f'    Mevcut Python: {cur[0]}.{cur[1]}')
        print(f'    Versiyon uyumsuzluğu nedeniyle çalışmayabilir!\x1b[0m')
check_python_version_compatibility()
Y = '\x1b[92m'
S = '\x1b[93m'
K = '\x1b[31m'
B = '\x1b[37m'
G = '\x1b[1;30;40m'
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def check_cython():
    try:
        import Cython
        from Cython.Build import cythonize
        return True
    except ImportError:
        return False

def check_nuitka():
    try:
        result = subprocess.run([sys.executable, '-m', 'nuitka', '--version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def check_gcc():
    try:
        result = subprocess.run(['gcc', '--version'], capture_output=True, timeout=5)
        return result.returncode == 0
    except:
        return False

def check_clang():
    try:
        result = subprocess.run(['clang', '--version'], capture_output=True, timeout=5)
        return result.returncode == 0
    except:
        return False

class CythonCompiler:

    def __init__(self, temp_dir):
        self.temp_dir = temp_dir
        self.available = check_cython()

    def compile_to_so(self, py_file, module_name=None):
        if not self.available:
            logger.warning('Cython yüklü değil!')
            return None
        if module_name is None:
            module_name = Path(py_file).stem
        pyx_file = os.path.join(self.temp_dir, f'{module_name}.pyx')
        if os.path.abspath(py_file) != os.path.abspath(pyx_file):
            shutil.copy(py_file, pyx_file)

        is_windows = platform.system() == 'Windows'
        is_arm = 'aarch64' in platform.machine().lower() or 'arm' in platform.machine().lower()

        if is_windows:
            extra_compile = ['/O2', '/GS-', '/GL', '/DNDEBUG']
            extra_link    = ['/LTCG', '/OPT:REF', '/OPT:ICF']
        else:
            extra_compile = [
                '-O2', '-g0', '-DNDEBUG',
                '-D_FORTIFY_SOURCE=0',
                '-DCYTHON_WITHOUT_ASSERTIONS=1',
                '-DCYTHON_CLINE_IN_TRACEBACK=0',
                '-ffunction-sections', '-fdata-sections',
                '-fno-common', '-fno-stack-protector',
                '-fomit-frame-pointer',
                '-fno-unwind-tables',
                '-fno-asynchronous-unwind-tables',
                '-fno-plt', '-fno-ident',
                '-fmerge-all-constants',
                '-funroll-loops',
            ]
            extra_link = [
                '-Wl,--strip-debug',
                '-Wl,--gc-sections',
                '-Wl,--as-needed',
                '-Wl,--build-id=none',
                '-Wl,--discard-locals',
            ]

        setup_file = os.path.join(self.temp_dir, 'setup_cython.py')
        setup_code = f"""\nimport os, sys, platform
from setuptools import setup, Extension
from Cython.Build import cythonize
from Cython.Compiler import Options

Options.annotate = False
Options.docstrings = False
Options.embed_pos_in_docstring = False

extra_compile = {extra_compile!r}
extra_link    = {extra_link!r}

ext = Extension(
    name='{module_name}',
    sources=['{pyx_file}'],
    extra_compile_args=extra_compile,
    extra_link_args=extra_link,
)

ext_modules = cythonize(
    [ext],
    compiler_directives={{
        'language_level': 3,
        'boundscheck': False,
        'wraparound': False,
        'cdivision': True,
        'cdivision_warnings': False,
        'cpow': True,
        'embedsignature': False,
        'emit_code_comments': False,
        'profile': False,
        'linetrace': False,
        'infer_types': True,
        'initializedcheck': False,
        'nonecheck': False,
        'overflowcheck': False,
        'binding': False,
        'annotation_typing': False,
        'optimize.use_switch': True,
        'optimize.unpack_method_calls': True,
        'warn.undeclared': False,
        'warn.unreachable': False,
        'warn.maybe_uninitialized': False,
        'warn.unused': False,
        'warn.unused_arg': False,
        'warn.unused_result': False,
        'show_performance_hints': False,
    }},
    annotate=False,
    quiet=True,
)

setup(
    name='{module_name}',
    ext_modules=ext_modules,
    zip_safe=False,
)
"""
        with open(setup_file, 'w') as f:
            f.write(setup_code)
        old_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            result = subprocess.run([sys.executable, 'setup_cython.py', 'build_ext', '--inplace'], capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.error(f'Cython derleme hatası: {result.stderr}')
                return None
            so_pattern = f'{module_name}*.so'
            pyd_pattern = f'{module_name}*.pyd'
            so_files = list(Path(self.temp_dir).glob(so_pattern))
            if not so_files:
                so_files = list(Path(self.temp_dir).glob(pyd_pattern))
            if so_files:
                so_path = str(so_files[0])
                if not is_windows:
                    os.system(
                        f"strip --strip-debug "
                        f"--remove-section=.comment "
                        f"--remove-section=.note "
                        f"--remove-section=.note.ABI-tag "
                        f"--remove-section=.note.gnu.build-id "
                        f"--remove-section=.note.gnu.property "
                        f"'{so_path}' 2>/dev/null"
                    )
                for c_file in Path(self.temp_dir).glob('*.c'):
                    try:
                        c_file.unlink()
                    except Exception:
                        pass
                logger.info(f'Cython derleme başarılı: {so_files[0].name}')
                return so_path
            return None
        except subprocess.TimeoutExpired:
            logger.error('Cython derleme zaman aşımı!')
            return None
        except Exception as e:
            logger.error(f'Cython hatası: {e}')
            return None
        finally:
            os.chdir(old_cwd)

    def create_obfuscated_wrapper(self, source_code, module_name='ninja_core'):
        # exec() yerine ctypes.pythonapi.PyEval_EvalCode kullan
        # .so içinde hiç PyCodeObject saklanmıyor → Cython decompiler kör
        hyp = HyperionObfuscator()
        vars = [hyp._randvar() for _ in range(20)]
        funcs = [hyp._randvar() for _ in range(10)]
        compressed = zlib.compress(source_code.encode('utf-8'), level=9)
        b64_data = base64.b64encode(compressed).decode('ascii')
        xor_keys = [random.randint(1, 255) for _ in range(3)]
        masks = [random.randint(1, 255) for _ in range(3)]
        blinded_keys = [xor_keys[i] ^ masks[i] for i in range(3)]

        cython_code = f'''# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: binding=False
# cython: embedsignature=False
# cython: emit_code_comments=False
# cython: profile=False
# cython: linetrace=False

from cpython.ref cimport PyObject
from libc.string cimport memset
import base64
import zlib
import sys
import ctypes

cdef int {vars[10]} = {blinded_keys[0]}
cdef int {vars[11]} = {masks[0]}
cdef int {vars[12]} = {blinded_keys[1]}
cdef int {vars[13]} = {masks[1]}
cdef int {vars[14]} = {blinded_keys[2]}
cdef int {vars[15]} = {masks[2]}

cdef bytes {vars[0]} = b"{b64_data}"

cdef bytes {funcs[0]}(bytes data, int key):
    cdef bytearray result = bytearray(len(data))
    cdef int i
    for i in range(len(data)):
        result[i] = data[i] ^ key
    return bytes(result)

cdef bytes {funcs[1]}():
    cdef int _k0 = {vars[10]} ^ {vars[11]}
    cdef int _k1 = {vars[12]} ^ {vars[13]}
    cdef int _k2 = {vars[14]} ^ {vars[15]}
    cdef bytes {vars[2]} = base64.b64decode({vars[0]})
    cdef bytes {vars[3]} = {funcs[0]}({vars[2]}, _k0)
    cdef bytes {vars[4]} = {funcs[0]}({vars[3]}, _k1)
    cdef bytes {vars[5]} = {funcs[0]}({vars[4]}, _k2)
    return zlib.decompress({vars[5]})

cdef void {funcs[2]}() except *:
    # exec() hiç kullanılmıyor → PyCodeObject .so içinde oluşmuyor
    # PyEval_EvalCode C API ile direkt çalıştır → memory'de anlık var, sonra wipe
    cdef bytes {vars[6]} = {funcs[1]}()
    cdef str {vars[7]} = {vars[6]}.decode('utf-8')

    # ctypes üzerinden C API — exec() hook'larını bypass eder
    _papi = ctypes.pythonapi
    _papi.Py_CompileString.restype = ctypes.py_object
    _papi.Py_CompileString.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]

    _code_obj = _papi.Py_CompileString(
        {vars[7]}.encode('utf-8'),
        b'<ninja>',
        ctypes.c_int(257)
    )

    _gl = {{'__name__': '__main__', '__builtins__': __builtins__}}
    _papi.PyEval_EvalCode.restype = ctypes.py_object
    _papi.PyEval_EvalCode.argtypes = [ctypes.py_object, ctypes.py_object, ctypes.py_object]
    _papi.PyEval_EvalCode(_code_obj, _gl, _gl)

    try:
        if hasattr(_code_obj, 'co_code'):
            _raw = bytes(_code_obj.co_code)
            if _raw:
                _buf = (ctypes.c_char * len(_raw)).from_address(id(_raw) + 32)
                ctypes.memset(_buf, 0, len(_raw))
    except Exception:
        pass
    del _code_obj, {vars[6]}, {vars[7]}

def {funcs[3]}():
    {funcs[2]}()

def run():
    {funcs[3]}()

if __name__ == '__main__':
    run()
'''
        data_bytes = base64.b64decode(b64_data)
        for key in reversed(xor_keys):
            data_bytes = bytes([b ^ key for b in data_bytes])
        new_b64 = base64.b64encode(data_bytes).decode('ascii')
        cython_code = cython_code.replace(b64_data, new_b64)
        pyx_file = os.path.join(self.temp_dir, f'{module_name}.pyx')
        with open(pyx_file, 'w', encoding='utf-8') as f:
            f.write(cython_code)
        return pyx_file

class NuitkaCompiler:

    def __init__(self, temp_dir):
        self.temp_dir = temp_dir
        self.available = check_nuitka()

    def compile_to_binary(self, py_file, output_name=None, standalone=False):
        if not self.available:
            logger.error('Nuitka yüklü değil! Kur: pip install nuitka')
            return None
        if output_name is None:
            output_name = Path(py_file).stem
        output_dir = os.path.join(self.temp_dir, 'nuitka_build')
        os.makedirs(output_dir, exist_ok=True)
        arch = platform.machine().lower()
        is_arm = 'aarch64' in arch or 'arm' in arch
        is_win = platform.system() == 'Windows'
        has_clang = check_clang()

        cmd = [sys.executable, '-m', 'nuitka',
               '--mode=module' if not standalone else '--mode=standalone',
               '--output-dir=' + output_dir,
               '--remove-output',
               '--no-pyi-file',
               '--nofollow-imports' if not standalone else '--follow-imports',
               '--assume-yes-for-downloads',
               '--python-flag=no_site',
               '--python-flag=no_warnings',
               '--python-flag=-S',
               '--python-flag=-OO',
               '--deployment',
               '--noinclude-setuptools-mode=nofollow',
               '--noinclude-pytest-mode=nofollow',
               '--noinclude-unittest-mode=nofollow',
               '--noinclude-IPython-mode=nofollow',
               '--low-memory',
        ]

        if has_clang:
            cmd.append('--clang')

        if not is_arm:
            cmd.append('--lto=yes')
            cmd.extend(['--jobs=2'])
        else:
            cmd.append('--no-progress-bar')

        if is_win and standalone:
            cmd.append('--windows-disable-console')

        if standalone:
            cmd.extend(['--onefile', '--static-libpython=auto'])
        cmd.append(py_file)
        logger.info(f'Nuitka derleniyor: {Path(py_file).name}')
        _cmd_str = ' '.join(cmd)
        logger.info(f'Komut: {_cmd_str}')
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=self.temp_dir)
            if result.returncode != 0:
                print(f'\x1b[31m[!] Nuitka derleme HATASI (kod {result.returncode}):\x1b[0m')
                if result.stderr:
                    print(result.stderr)
                if result.stdout:
                    print(result.stdout)
                return None
            if standalone:
                bin_files = list(Path(output_dir).glob(f'{output_name}*'))
                bin_files = [f for f in bin_files if f.is_file() and f.suffix not in ['.py', '.pyx', '.c', '.h']]
            else:
                bin_files = list(Path(output_dir).glob(f'{output_name}*.so'))
                if not bin_files:
                    bin_files = list(Path(output_dir).glob(f'{output_name}*.pyd'))
                if not bin_files:
                    bin_files = list(Path(output_dir).glob(f'{output_name}*.cpython*.so'))
                if not bin_files:
                    bin_files = list(Path(self.temp_dir).rglob(f'{output_name}*.so'))
            if bin_files:
                logger.info(f'Nuitka derleme başarılı: {bin_files[0].name}')
                return str(bin_files[0])
            print(f'\x1b[31m[!] Nuitka derlendi ama .so dosyası bulunamadı!\x1b[0m')
            print(f'    Aranan dizin: {output_dir}')
            _dir_files = list(Path(output_dir).iterdir()) if Path(output_dir).exists() else 'Dizin yok'
            print(f'    Mevcut dosyalar: {_dir_files}')
            return None
        except subprocess.TimeoutExpired:
            print(f'\x1b[31m[!] Nuitka derleme ZAMAN AŞIMI (10 dakika)!\x1b[0m')
            return None
        except FileNotFoundError as e:
            print(f'\x1b[31m[!] Nuitka bulunamadı: {e}\x1b[0m')
            print('    Kur: pip install nuitka')
            return None
        except Exception as e:
            print(f'\x1b[31m[!] Nuitka beklenmeyen hata: {type(e).__name__}: {e}\x1b[0m')
            import traceback
            traceback.print_exc()
            return None

    def compile_module(self, py_file):
        return self.compile_to_binary(py_file, standalone=False)

    def compile_standalone(self, py_file):
        return self.compile_to_binary(py_file, standalone=True)

    def compile_with_embedded_cython(self, wrapper_py: str, cython_so: str) -> str | None:
        if not self.available:
            logger.error('Nuitka yüklü değil!')
            return None

        with open(cython_so, 'rb') as f:
            so_bytes = f.read()
        so_b64 = base64.b64encode(so_bytes).decode('ascii')
        cython_mod = Path(cython_so).name.split('.')[0]

        embed_src = f'''import base64 as _b64, tempfile as _tf, ctypes as _ct, os as _os, sys as _sys

_SO_DATA = b"{so_b64}"

def _load_embedded():
    _raw = _b64.b64decode(_SO_DATA)
    _tmp = _tf.NamedTemporaryFile(suffix='.so', delete=False, prefix='_nj_')
    try:
        _tmp.write(_raw)
        _tmp.close()
        _os.chmod(_tmp.name, 0o755)
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location('{cython_mod}', _tmp.name)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod
    except Exception as _e:
        try: _os.unlink(_tmp.name)
        except: pass
        raise _e

_ninja_mod = _load_embedded()

def run():
    if hasattr(_ninja_mod, 'run'):
        _ninja_mod.run()

if __name__ == '__main__':
    run()
'''
        embed_py = os.path.join(self.temp_dir, 'ninja_embed.py')
        with open(embed_py, 'w', encoding='utf-8') as f:
            f.write(embed_src)

        output_dir = os.path.join(self.temp_dir, 'nuitka_embed_build')
        os.makedirs(output_dir, exist_ok=True)

        arch      = platform.machine().lower()
        is_arm    = 'aarch64' in arch or 'arm' in arch
        has_clang = check_clang()

        cmd = [
            sys.executable, '-m', 'nuitka',
            '--mode=module',
            f'--output-dir={output_dir}',
            '--remove-output',
            '--no-pyi-file',
            '--nofollow-imports',
            '--assume-yes-for-downloads',
            '--python-flag=no_site',
            '--python-flag=no_warnings',
            '--python-flag=-S',
            '--python-flag=-OO',
            '--deployment',
            '--low-memory',
            '--no-progress-bar',
        ]

        if has_clang:
            cmd.append('--clang')
        if not is_arm:
            cmd.extend(['--lto=yes', '--jobs=2'])

        cmd.append(embed_py)

        logger.info(f'Nuitka → base64 embedded Cython derleniyor...')
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                print(f'\x1b[31m[!] Nuitka embed HATASI:\x1b[0m')
                if result.stderr: print(result.stderr[-2000:])
                return None

            so_files = list(Path(output_dir).rglob('*.so'))
            if not so_files:
                so_files = list(Path(output_dir).rglob('*.pyd'))
            if so_files:
                logger.info(f'Nuitka embed başarılı: {so_files[0].name}')
                return str(so_files[0])
            print('\x1b[31m[!] Nuitka embed derlendi ama .so bulunamadı!\x1b[0m')
            return None
        except subprocess.TimeoutExpired:
            print('\x1b[31m[!] Nuitka embed zaman aşımı!\x1b[0m')
            return None
        except Exception as _e:
            print(f'\x1b[31m[!] Nuitka embed beklenmeyen hata: {_e}\x1b[0m')
            return None

class HyperionObfuscator:

    def __init__(self):
        self.var_map = {}
        self.string_map = {}

    def _randvar(self):
        patterns = [lambda: ''.join((random.choice('lI') for _ in range(random.randint(15, 25)))), lambda: 'O' + ''.join((random.choice('O0o') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('DO') for _ in range(random.randint(15, 25)))), lambda: 'S' + ''.join((random.choice('S2') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('MN') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('mn') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('XW') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('xw') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('JIL') for _ in range(random.randint(15, 25)))), lambda: ''.join((random.choice('jil') for _ in range(random.randint(15, 25))))]
        return random.choice(patterns)()

    def _hex_encode(self, s):
        return ''.join((f'\\x{hexlify(c.encode()).decode()}' for c in s))

    def _obf_int(self, num):
        if num == 0:
            return '(int())'
        r = random.randint(100000, 9999999)
        if num > 0:
            return f'({self._underscore(r)}+(-{self._underscore(r - num)}))'
        else:
            return f'(-{self._underscore(abs(num) + r)}+{self._underscore(r)})'

    def _underscore(self, num):
        s = str(abs(num))
        return '_'.join(s)

    def _obf_bool(self, val):
        if val:
            return "bool((~(not bool('')))|((bool('x'))&(not bool(''))))"
        else:
            return "not(bool(str(bool(''))))"

    def _obf_string(self, s):
        hex_str = hexlify(s.encode()).decode()
        return f"__import__('binascii').unhexlify('{hex_str}').decode('utf-8')"

    def _reverse_string(self, s):
        reversed_s = s[::-1]
        return f"'{reversed_s}'[::-1]"

    def generate_lambda_chain(self, code):
        var1 = self._randvar()
        var2 = self._randvar()
        var3 = self._randvar()
        compressed = zlib.compress(code.encode('utf-8'))
        b64_data = base64.b64encode(compressed).decode()
        return f"(lambda {var1}:(lambda {var2}:{var2}(__import__('zlib').decompress(__import__('base64').b64decode({var1})))))(lambda {var3}:exec({var3})))('{b64_data}')"

    def generate_fake_class(self, real_code, data_parts):
        gen = [self._randvar() for _ in range(25)]
        fake_vars = ['MemoryAccess', 'StackOverflow', 'System', 'Divide', 'Product', 'CallFunction', 'Math', 'Calculate', 'Hypothesis', 'Frame', 'DetectVar', 'Substract', 'Theory', 'Statistics', 'Random']
        random.shuffle(fake_vars)
        rand_int = lambda: random.randint(-100000, 100000)
        rand_op = lambda: random.choice(['+', '-', '*'])
        rand_type = lambda: random.choice(['type', 'None', 'Ellipsis', 'True', 'False', 'str', 'int'])
        data_vars = {self._randvar(): part for part in data_parts}
        vars_code = '\n'.join((f"        {gen[0]}.{gen[19]}('{k}', {repr(v)})" for k, v in data_vars.items()))
        data_concat = '+'.join((f"{gen[0]}.{gen[18]}('{k}')" for k in data_vars.keys()))
        return f"\nfrom builtins import *\nfrom math import prod as {gen[5]}\n\n__obfuscator__ = 'NinjaEnc'\n__version__ = '3.0'\n__author__ = 'Buğra'\n\n{gen[11]}, {gen[12]}, {gen[13]}, {gen[14]}, {gen[15]}, {gen[17]}, {gen[24]} = exec, str, tuple, map, ord, globals, type\n\nclass {gen[0]}:\n    _data = {{}}\n\n    def __init__(self, {gen[4]}):\n        self.{gen[3]} = {gen[5]}(({gen[4]}, {rand_int()}))\n        self.{gen[1]}({gen[6]}={rand_int()})\n\n    def {gen[1]}(self, {gen[6]} = {rand_type()}):\n        self.{gen[3]} {rand_op()}= {rand_int()} {rand_op()} {gen[6]} if isinstance({gen[6]}, int) else 0\n        try:\n            {{{repr(self._randvar())}: {repr(self._randvar())}}}\n        except (OSError, TypeError):\n            pass\n\n    def {gen[2]}(self, {gen[7]} = {rand_int()}):\n        {gen[7]} {rand_op()}= {rand_int()} {rand_op()} {rand_int()}\n        self.{gen[8]} != {rand_type()}\n\n    @staticmethod\n    def {gen[18]}({gen[20]} = {rand_type()}):\n        return {gen[0]}._data.get({gen[20]}, '')\n\n    @staticmethod\n    def {gen[19]}({gen[21]} = '', {gen[22]} = {rand_type()}):\n        {gen[0]}._data[{gen[21]}] = {gen[22]}\n\n    @staticmethod\n    def execute(code = str):\n        return {gen[11]}({gen[12]}({gen[13]}({gen[14]}({gen[15]}, code))))\n\n    @property\n    def {gen[8]}(self):\n        self.{gen[9]} = '<__main__.{random.choice(fake_vars)} object at 0x00000{random.randint(1000, 9999)}BE{random.randint(10000, 99999)}>'\n        return (self.{gen[9]}, {gen[0]}.{gen[8]})\n\nif __name__ == '__main__':\n    try:\n        {gen[10]} = {gen[0]}({gen[4]} = {rand_int()} {rand_op()} {rand_int()})\n\n{vars_code}\n\n        {real_code.replace('DATACONCAT', data_concat)}\n\n    except Exception as {gen[16]}:\n        if {random.randint(100000, 499999)} > {random.randint(500000, 9999999)}:\n            {gen[0]}.execute(code = {gen[12]}({gen[16]}))\n"

class XORObfuscator:

    @staticmethod
    def encode_string(s, key=None):
        if key is None:
            key = random.randint(1, 255)
        encoded_bytes = [ord(c) ^ key for c in s]
        return f'(lambda _s,_k="": "".join(chr(_b^{key}) for _b in {encoded_bytes}))(None)'

    @staticmethod
    def decode_string(encoded_bytes, key):
        return ''.join((chr(b ^ key) for b in encoded_bytes))

    @staticmethod
    def multi_xor_encode(data, keys=None):
        if keys is None:
            keys = [random.randint(1, 255) for _ in range(3)]
        result = data
        for key in keys:
            if isinstance(result, str):
                result = bytes([ord(c) ^ key for c in result])
            else:
                result = bytes([b ^ key for b in result])
        return (result, keys)

class Ascii85Encoder:

    @staticmethod
    def encode(binary_data, padding_size=None):
        if padding_size is None:
            padding_size = random.randint(5000, 15000)
        random_padding = bytes([random.randint(0, 255) for _ in range(padding_size)])
        original_size = len(binary_data)
        size_bytes = original_size.to_bytes(4, byteorder='big')
        padded_data = size_bytes + binary_data + random_padding
        b64_encoded = base64.b64encode(padded_data)
        final_encoded = base64.a85encode(b64_encoded)
        return final_encoded.decode('ascii')

    @staticmethod
    def decode(encoded_str):
        clean_data = encoded_str.replace('\n', '')
        first_decode = base64.a85decode(clean_data.encode('ascii'))
        padded_data = base64.b64decode(first_decode)
        original_size = int.from_bytes(padded_data[0:4], byteorder='big')
        return padded_data[4:4 + original_size]

class AESEncryptor:

    @staticmethod
    def is_available():
        try:
            from Crypto.Cipher import AES
            return True
        except ImportError:
            return False

    @staticmethod
    def derive_runtime_key_code(encrypted_key_b64: str) -> str:
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(10)]
        xor_mask = random.randint(1, 255)
        key_bytes = base64.b64decode(encrypted_key_b64)
        masked_key = bytes(b ^ xor_mask for b in key_bytes)
        masked_b64 = base64.b64encode(masked_key).decode('ascii')
        return f'''
def {v[0]}():
    import hashlib as _h, os as _o, platform as _pl, base64 as _b
    _parts = []
    try: _parts.append(_o.uname().nodename.encode())
    except Exception: _parts.append(b"host")
    try: _parts.append(_pl.machine().encode())
    except Exception: _parts.append(b"arch")
    try: _parts.append(str(_o.cpu_count() or 2).encode())
    except Exception: _parts.append(b"2")
    _machine_hash = _h.sha256(b":".join(_parts)).digest()
    _mk = {xor_mask}
    _masked = _b.b64decode("{masked_b64}")
    _raw_key = bytes(b ^ _mk for b in _masked)
    _final = bytes(a ^ b for a, b in zip(_raw_key, _machine_hash * (len(_raw_key) // 32 + 1)))
    return _final[:32]
{v[0]}()
'''

    @staticmethod
    def derive_key(password: bytes, salt: bytes, iterations: int=200000) -> bytes:
        import hmac
        return hashlib.pbkdf2_hmac('sha256', password, salt, iterations, dklen=32)

    @staticmethod
    def encrypt(data, key=None):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
            MAGIC = b'NJNC'
            if isinstance(data, str):
                data = data.encode('utf-8')
            salt = os.urandom(16)
            iv = os.urandom(16)
            iterations = random.randint(150000, 250000)
            if key is None:
                password = os.urandom(32)
                derived_key = AESEncryptor.derive_key(password, salt, iterations)
                actual_key = derived_key
                stored_key = password
            else:
                derived_key = AESEncryptor.derive_key(key if isinstance(key, bytes) else key.encode(), salt, iterations)
                actual_key = derived_key
                stored_key = key
            cipher = AES.new(actual_key, AES.MODE_CBC, iv)
            encrypted = cipher.encrypt(pad(data, AES.block_size))
            iter_bytes = iterations.to_bytes(4, byteorder='big')
            result = MAGIC + salt + iter_bytes + iv + encrypted
            return (result, stored_key)
        except ImportError:
            print('\x1b[93m[!] pycryptodome yüklü değil, AES atlanıyor. Kur: pip install pycryptodome\x1b[0m')
            return (None, None)
        except Exception as e:
            print(f'\x1b[31m[!] AES şifreleme hatası: {type(e).__name__}: {e}\x1b[0m')
            return (None, None)

    @staticmethod
    def decrypt(encrypted_data, key):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            MAGIC = b'NJNC'
            if encrypted_data[:4] != MAGIC:
                raise ValueError('Geçersiz magic bytes — bu veri AESEncryptor ile şifrelenmemiş!')
            salt = encrypted_data[4:20]
            iterations = int.from_bytes(encrypted_data[20:24], byteorder='big')
            iv = encrypted_data[24:40]
            ciphertext = encrypted_data[40:]
            derived_key = AESEncryptor.derive_key(key if isinstance(key, bytes) else key.encode(), salt, iterations)
            cipher = AES.new(derived_key, AES.MODE_CBC, iv)
            return unpad(cipher.decrypt(ciphertext), AES.block_size)
        except Exception as e:
            print(f'\x1b[31m[!] AES çözme hatası: {type(e).__name__}: {e}\x1b[0m')
            return None

class ChaCha20Encryptor:
    MAGIC = b'NJCC'

    @staticmethod
    def is_available():
        try:
            from Crypto.Cipher import ChaCha20_Poly1305
            return True
        except ImportError:
            return False

    @staticmethod
    def encrypt(data: bytes) -> tuple:
        try:
            from Crypto.Cipher import ChaCha20_Poly1305
            if isinstance(data, str):
                data = data.encode('utf-8')
            key = os.urandom(32)
            nonce = os.urandom(12)
            cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
            ciphertext, tag = cipher.encrypt_and_digest(data)
            result = ChaCha20Encryptor.MAGIC + nonce + tag + ciphertext
            return result, key
        except Exception as e:
            logger.warning(f'ChaCha20 şifreleme hatası: {e}')
            return None, None

    @staticmethod
    def decrypt(data: bytes, key: bytes):
        try:
            from Crypto.Cipher import ChaCha20_Poly1305
            if data[:4] != ChaCha20Encryptor.MAGIC:
                raise ValueError('Geçersiz magic')
            nonce = data[4:16]
            tag   = data[16:32]
            ct    = data[32:]
            cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
            return cipher.decrypt_and_verify(ct, tag)
        except Exception as e:
            logger.warning(f'ChaCha20 çözme hatası: {e}')
            return None

    @staticmethod
    def generate_decrypt_code(var_data: str, var_key_b64: str, var_out: str) -> str:
        return f'''
try:
    from Crypto.Cipher import ChaCha20_Poly1305 as _CC
    import base64 as _cc_b64
    _cc_key = _cc_b64.b64decode({var_key_b64})
    _cc_nonce = {var_data}[4:16]
    _cc_tag   = {var_data}[16:32]
    _cc_ct    = {var_data}[32:]
    _cc_cip   = _CC.new(key=_cc_key, nonce=_cc_nonce)
    {var_out} = _cc_cip.decrypt_and_verify(_cc_ct, _cc_tag)
    del _cc_key, _cc_nonce, _cc_tag, _cc_ct, _cc_cip
except Exception:
    {var_out} = {var_data}
'''

class ImportHook:

    @staticmethod
    def generate_hook_code() -> str:
        fake_modules = {
            '_crypto_core':   'raise ImportError("No module named _crypto_core")',
            '_hashlib_ext':   'raise ImportError("No module named _hashlib_ext")',
            '_ninja_runtime': 'raise ImportError("No module named _ninja_runtime")',
            '_obf_engine':    'raise ImportError("No module named _obf_engine")',
        }
        fake_mod_repr = repr(fake_modules)
        return f'''
import sys as _IH_sys

class _IH_FakeLoader:
    def __init__(self, name):
        self._name = name
    def create_module(self, spec): return None
    def exec_module(self, module):
        module.__doc__ = "Protected module"
        module.__version__ = "1.0.0"
        module.__file__ = "<protected>"

class _IH_MetaFinder:
    _FAKE = {fake_mod_repr}
    _REAL_FINDER = None

    def find_spec(self, fullname, path, target=None):
        if fullname in self._FAKE:
            import importlib.util as _ilu
            spec = _ilu.spec_from_loader(fullname, _IH_FakeLoader(fullname))
            return spec
        return None

_IH_hook = _IH_MetaFinder()
if not any(type(f).__name__ == "_IH_MetaFinder" for f in _IH_sys.meta_path):
    _IH_sys.meta_path.insert(0, _IH_hook)
del _IH_hook
'''

class CodeObjectMutator:

    @staticmethod
    def mutate_co_consts(code_bytes: bytes) -> bytes:
        try:
            co = marshal.loads(code_bytes)

            def _mutate(c):
                try:
                    fake_consts = (
                        b'\x00' * random.randint(4, 16),
                        random.randint(0x1337, 0xDEADBEEF),
                        'ninja_' + hashlib.md5(os.urandom(4)).hexdigest()[:8],
                    )
                    new_consts = tuple(
                        _mutate(x) if isinstance(x, types.CodeType) else x
                        for x in c.co_consts
                    ) + fake_consts

                    try:
                        lnotab = bytearray(c.co_lnotab)
                        for i in range(1, len(lnotab), 2):
                            lnotab[i] = (lnotab[i] + random.randint(1, 10)) & 0xFF
                        new_lnotab = bytes(lnotab)
                    except Exception:
                        new_lnotab = c.co_lnotab

                    return c.replace(co_consts=new_consts, co_lnotab=new_lnotab)
                except Exception:
                    return c

            mutated = _mutate(co)
            return marshal.dumps(mutated)
        except Exception as e:
            logger.warning(f'CodeObjectMutator atlandı: {e}')
            return code_bytes

    @staticmethod
    def generate_runtime_mutation_code() -> str:
        fake_vals = [
            repr(b'\x00' * 8),
            repr(0xDEADBEEF),
            repr('_ninja_protected'),
        ]
        return f'''
import types as _COM_ty, marshal as _COM_ma, random as _COM_rnd

def _COM_mutate(co):
    try:
        _fake = ({fake_vals[0]}, {fake_vals[1]}, {fake_vals[2]})
        _new_consts = tuple(
            _COM_mutate(x) if isinstance(x, _COM_ty.CodeType) else x
            for x in co.co_consts
        ) + _fake
        try:
            _ln = bytearray(co.co_lnotab)
            for _i in range(1, len(_ln), 2):
                _ln[_i] = (_ln[_i] + _COM_rnd.randint(1, 5)) & 0xFF
            return co.replace(co_consts=_new_consts, co_lnotab=bytes(_ln))
        except Exception:
            return co.replace(co_consts=_new_consts)
    except Exception:
        return co
'''

class PolymorphicDecryptor:

    PATTERNS = ['loop', 'map_lambda', 'bytearray_loop', 'list_comp', 'generator', 'recursive']

    @staticmethod
    def generate(var_enc: str, var_key: str, var_out: str) -> str:
        pattern = random.choice(PolymorphicDecryptor.PATTERNS)

        if pattern == 'loop':
            return f'''
{var_out} = bytearray(len({var_enc}))
for _pi, _pb in enumerate({var_enc}):
    {var_out}[_pi] = _pb ^ {var_key}[_pi % len({var_key})]
{var_out} = bytes({var_out})
'''
        elif pattern == 'map_lambda':
            return f'''
{var_out} = bytes(map(lambda _pi_b: _pi_b[1] ^ {var_key}[_pi_b[0] % len({var_key})], enumerate({var_enc})))
'''
        elif pattern == 'bytearray_loop':
            return f'''
_pd_buf = bytearray()
_pd_kl  = len({var_key})
for _pd_i in range(len({var_enc})):
    _pd_buf.append({var_enc}[_pd_i] ^ {var_key}[_pd_i % _pd_kl])
{var_out} = bytes(_pd_buf)
del _pd_buf, _pd_kl
'''
        elif pattern == 'list_comp':
            return f'''
{var_out} = bytes([{var_enc}[_lc_i] ^ {var_key}[_lc_i % len({var_key})] for _lc_i in range(len({var_enc}))])
'''
        elif pattern == 'generator':
            return f'''
def _pg_dec(_d, _k):
    _kl = len(_k)
    for _i, _b in enumerate(_d):
        yield _b ^ _k[_i % _kl]
{var_out} = bytes(_pg_dec({var_enc}, {var_key}))
del _pg_dec
'''
        else:
            return f'''
def _pr_dec(_d, _k, _i=0, _acc=None):
    if _acc is None: _acc = bytearray()
    if _i >= len(_d): return bytes(_acc)
    _acc.append(_d[_i] ^ _k[_i % len(_k)])
    return _pr_dec(_d, _k, _i+1, _acc)
{var_out} = _pr_dec({var_enc}, {var_key})
del _pr_dec
'''

    @staticmethod
    def generate_multi_stage(data: bytes) -> tuple:
        key1 = os.urandom(random.randint(16, 32))
        stage1 = bytes(b ^ key1[i % len(key1)] for i, b in enumerate(data))

        rot = random.randint(1, 7)
        stage2 = bytes(((b << rot) | (b >> (8 - rot))) & 0xFF for b in stage1)

        key2 = os.urandom(random.randint(16, 32))
        stage3 = bytes(b ^ key2[i % len(key2)] for i, b in enumerate(stage2))

        params = {
            'key1': base64.b64encode(key1).decode(),
            'key2': base64.b64encode(key2).decode(),
            'rot':  rot,
        }
        return stage3, params

    @staticmethod
    def generate_multi_stage_decrypt(var_enc: str, params: dict, var_out: str) -> str:
        k1 = params['key1']
        k2 = params['key2']
        rot = params['rot']
        unrot = 8 - rot

        p1 = random.choice(PolymorphicDecryptor.PATTERNS)
        p2 = random.choice(PolymorphicDecryptor.PATTERNS)
        p3 = random.choice(PolymorphicDecryptor.PATTERNS)

        dec3 = PolymorphicDecryptor.generate(var_enc, f"__import__('base64').b64decode('{k2}')", '_pd_s3')
        dec2 = f"_pd_s2 = bytes(((b >> {rot}) | (b << {unrot})) & 0xFF for b in _pd_s3)"
        dec1 = PolymorphicDecryptor.generate('_pd_s2', f"__import__('base64').b64decode('{k1}')", var_out)

        return f'''
import base64 as _pd_b64
{dec3}
{dec2}
{dec1}
del _pd_s3, _pd_s2
'''

class MetamorphicStager:

    ALL_STAGES = [
        # 'str_table' — ana pipeline adım 5'te yapılıyor, çift uygulama bozuyor
        # 'cf_flat'   — ana pipeline adım 3'te yapılıyor, çift uygulama MBA ile çakışıyor
        'str_enc',
        'dead_code',
        'opaque',
        'cf_obf',
        'mba',
    ]

    @staticmethod
    def get_random_order() -> list:
        stages = MetamorphicStager.ALL_STAGES.copy()
        random.shuffle(stages)
        return stages

    @staticmethod
    def apply(encoder, source: str, stages: list) -> str:
        result = source
        stage_map = {
            'str_table': lambda s: encoder.str_table.encrypt_to_table(s),
            'str_enc':   lambda s: encoder.string_enc.encrypt_all_strings_in_code(s),
            'dead_code': lambda s: encoder.dead_code.inject_into_source(s, count=8),
            'opaque':    lambda s: encoder.opaque.wrap_with_opaques(s),
            'cf_obf':    lambda s: encoder.cf_obf.inject_fake_branches(s),
            'mba':       lambda s: encoder.mba.transform_source(s),
            'cf_flat':   lambda s: encoder.cf_flatten.flatten_source(s),
        }
        for stage in stages:
            try:
                fn = stage_map.get(stage)
                if fn:
                    result = fn(result)
                    logger.info(f'MetamorphicStager: {stage} uygulandı')
            except Exception as e:
                logger.warning(f'MetamorphicStager: {stage} atlandı — {e}')
        return result

class MainPyGenerator:

    def __init__(self):
        self.xor = XORObfuscator()
        self.hyp = HyperionObfuscator()

    def generate(self, has_native=False, native_fname='', xor_keys=None, aes_key_b64=None):
        v = [self.hyp._randvar() for _ in range(20)]
        xor_keys = xor_keys or [random.randint(1,255), random.randint(1,255), random.randint(1,255)]
        k0, k1, k2 = xor_keys[0], xor_keys[1], xor_keys[2]

        _mk0 = random.randint(1, 255)
        _mk1 = random.randint(1, 255)
        _mk2 = random.randint(1, 255)
        _bk0 = k0 ^ _mk0
        _bk1 = k1 ^ _mk1
        _bk2 = k2 ^ _mk2

        _xor_order = list(range(3))
        random.shuffle(_xor_order)
        _keys_ordered = [(_bk0, _mk0), (_bk1, _mk1), (_bk2, _mk2)]

        def _xor_step(src_var, dst_var, bk, mk):
            return f'        {dst_var}=bytes(b^({bk}^{mk}) for b in {src_var})\n'

        _step_vars = [v[3], v[4], v[5], v[16] if len(v) > 16 else self.hyp._randvar()]
        _xor_steps = ''
        _cur = v[3]
        for _i, _oi in enumerate(_xor_order):
            _nxt = v[4+_i] if _i < 2 else v[3]
            _bk, _mk = _keys_ordered[_oi]
            _xor_steps += _xor_step(_cur, _nxt, _bk, _mk)
            _cur = _nxt

        _wd_var = self.hyp._randvar()
        _wd_flag = self.hyp._randvar()
        _watchdog_block = f'''
import threading as _WD_th, sys as _WD_sy, gc as _WD_gc
{_wd_flag} = True
def {_wd_var}():
    import time as _WD_tm
    while {_wd_flag}:
        try:
            if _WD_sy.gettrace() is not None:
                _WD_sy.exit()
            _mods = list(_WD_sy.modules.keys())
            _bad = ['bdb','pdb','pydevd','debugpy','pydev','_pydev']
            if any(m in _mods for m in _bad):
                _WD_sy.exit()
            _objs = _WD_gc.get_objects()
            for _o in _objs:
                if hasattr(_o,'__class__') and 'Bdb' in str(type(_o).__mro__):
                    _WD_sy.exit()
        except SystemExit:
            import os as _WD_os
            _WD_os._exit(1)
        except Exception:
            pass
        _WD_tm.sleep(0.5)
_WD_t = _WD_th.Thread(target={_wd_var}, daemon=True)
_WD_t.start()
'''

        aes_block = ''
        if aes_key_b64:
            aes_block = f'''    try:
        import hashlib as _hl
        from Crypto.Cipher import AES as _AES
        from Crypto.Util.Padding import unpad as _unp
        _pw=__import__('base64').b64decode('{aes_key_b64}')
        _s={v[3]}[4:20];_it=int.from_bytes({v[3]}[20:24],'big')
        _iv={v[3]}[24:40];_ct={v[3]}[40:]
        _dk=_hl.pbkdf2_hmac('sha256',_pw,_s,_it,dklen=32)
        {v[3]}=_unp(_AES.new(_dk,_AES.MODE_CBC,_iv).decrypt(_ct),_AES.block_size)
        del _pw,_s,_it,_iv,_ct,_dk
    except Exception:pass
'''

        native_block = ''
        if native_fname:
            native_block = f'''
        _nf='{native_fname}'
        if _nf:
            _np=_O.path.join(_d,_nf)
            if _O.path.exists(_np):
                try:
                    import importlib.util as _ilu
                    _O.chmod(_np,0o755)
                    _spec=_ilu.spec_from_file_location('_ninja_mod',_np)
                    _mod=_ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    if hasattr(_mod,'run'):_mod.run()
                    return
                except Exception:pass
'''

        bad_zip_msg = self.xor.encode_string('Hata: Bozuk arsiv')
        error_msg   = self.xor.encode_string('Hata: %s')
        main_check  = self.xor.encode_string('__main__')

        _ad_block = '\nimport sys as _AD_sy,os as _AD_os,time as _AD_tm,platform as _AD_pl,socket as _AD_sk,threading as _AD_th\n\n_AD_IS_ANDROID = _AD_os.path.exists("/system/build.prop") or _AD_os.path.exists("/data/data")\n_AD_IS_ARM = _AD_pl.machine().lower() in ("aarch64","arm","armv7l","armv8l")\n\ndef _AD_chk_trace():\n    if _AD_IS_ANDROID: return False\n    try:\n        if _AD_sy.gettrace() is not None: return True\n    except Exception: pass\n    try:\n        if _AD_sy.flags.debug: return True\n    except Exception: pass\n    return False\n\ndef _AD_chk_tracer():\n    try:\n        with open("/proc/self/status","r") as _f:\n            for _l in _f:\n                if _l.startswith("TracerPid:") and int(_l.split(":")[1].strip()) != 0:\n                    return True\n    except Exception: pass\n    return False\n\ndef _AD_chk_maps():\n    _bad = ["frida","frida-server","frida-agent","gdb","lldb","strace","radare2","ida"]\n    if not _AD_IS_ANDROID:\n        _bad += ["pycharm","pydev","debugpy","pydevd"]\n    try:\n        with open("/proc/self/maps","r") as _f:\n            _c = _f.read().lower()\n            for _s in _bad:\n                if _s in _c: return True\n    except Exception: pass\n    try:\n        _exe = _AD_os.readlink("/proc/self/exe").lower()\n        for _s in _bad:\n            if _s in _exe: return True\n    except Exception: pass\n    return False\n\ndef _AD_chk_frida():\n    try:\n        for _p in [27042, 27043, 10900]:\n            _s = _AD_sk.socket()\n            _s.settimeout(0.05)\n            if _s.connect_ex(("127.0.0.1",_p)) == 0:\n                _s.close(); return True\n            _s.close()\n    except Exception: pass\n    try:\n        if any("frida" in _t.name.lower() for _t in _AD_th.enumerate()): return True\n    except Exception: pass\n    try:\n        _ld = _AD_os.environ.get("LD_PRELOAD","").lower()\n        if _ld and any(x in _ld for x in ["frida","gadget","interpose"]): return True\n    except Exception: pass\n    try:\n        _fd_dir = "/proc/self/fd"\n        if _AD_os.path.exists(_fd_dir):\n            for _fd in _AD_os.listdir(_fd_dir):\n                try:\n                    _lnk = _AD_os.readlink(_AD_os.path.join(_fd_dir,_fd)).lower()\n                    if "frida" in _lnk or "gum" in _lnk: return True\n                except Exception: pass\n    except Exception: pass\n    return False\n\ndef _AD_chk_parent():\n    try:\n        _pp = _AD_os.popen("ps -o comm= -p "+str(_AD_os.getppid())).read().strip().lower()\n        for _s in ["gdb","lldb","strace","frida","radare2","ida"]:\n            if _s in _pp: return True\n    except Exception: pass\n    return False\n\ndef _AD_chk_timing():\n    try:\n        _t0 = _AD_tm.monotonic()\n        _acc = 0\n        for _ii in range(10000): _acc += _ii\n        _base = _AD_tm.monotonic() - _t0\n        _t1 = _AD_tm.monotonic()\n        _acc2 = 0\n        for _ii in range(10000): _acc2 += _ii\n        _real = _AD_tm.monotonic() - _t1\n        _limit = 3.0 if _AD_IS_ARM else 1.0\n        if _base > 0 and _real > _base * 10: return True\n        if _real > _limit: return True\n    except Exception: pass\n    return False\n\ndef _AD_run():\n    _sc = 0\n    if _AD_chk_trace():  _sc += 5\n    if _AD_chk_tracer(): _sc += 5\n    if _AD_chk_maps():   _sc += 4\n    if _AD_chk_frida():  _sc += 5\n    if _AD_chk_parent(): _sc += 3\n    if _AD_chk_timing(): _sc += 3\n    _threshold = 8\n    if _sc < _threshold: return\n    _kill = [\n        lambda: _AD_os._exit(0),\n        lambda: (_ for _ in ()).throw(MemoryError()),\n        lambda: (_ for _ in ()).throw(ImportError("No module named _hashcore")),\n        lambda: (_ for _ in ()).throw(OSError(22,"Invalid argument")),\n        lambda: _AD_os.kill(_AD_os.getpid(),9),\n        lambda: (_ for _ in ()).throw(SystemExit(1)),\n    ]\n    _kill[_sc % len(_kill)]()\n\n_AD_run()\n'

        _ih_block = ImportHook.generate_hook_code()
        _com_block = CodeObjectMutator.generate_runtime_mutation_code()

        code = f'''{_ad_block}
{_watchdog_block}
{_ih_block}
{_com_block}
import zipfile as _Z,os as _O,shutil as _SH,tempfile as _T,sys as _S,base64 as _B,random as _R,hashlib as _HL,zlib as _ZL
def _run():
    _d=_T.mkdtemp()
    try:
        _f=_O.path.abspath(_S.argv[0])
        with _Z.ZipFile(_f,'r') as _zf:
            _zf.extractall(_d)
{native_block}        _sp=_O.path.join(_d,'__script__.bin')
        if not _O.path.exists(_sp):
            _sp=_O.path.join(_d,'__script__.py')
            with open(_sp,'r') as _fh:
                exec(compile(_fh.read(),_sp,'exec'),{{'__name__':'__main__','__file__':_sp}})
            return
        with open(_sp,'rb') as _fh:
            {v[3]}=_fh.read()
{_xor_steps}{aes_block}        import zlib as _zl,marshal as _m,types as _ty,ctypes as _ctypes
        {v[6]}=_zl.decompress({v[3]})
        {v[7]}=_m.loads({v[6]})
        del {v[3]},{v[4]},{v[5]},{v[6]}
        {v[8]}=_ty.ModuleType('__main__')
        import sys as _sys_tmp,os as _os_tmp
        {v[8]}.__dict__.update({{'__name__':'__main__','__builtins__':__builtins__,'__file__':_sp,'sys':_sys_tmp,'os':_os_tmp}})
        try:
            _papi=_ctypes.pythonapi
            _papi.PyEval_EvalCode.restype=_ctypes.py_object
            _papi.PyEval_EvalCode.argtypes=[_ctypes.py_object,_ctypes.py_object,_ctypes.py_object]
            _papi.PyEval_EvalCode({v[7]},{v[8]}.__dict__,{v[8]}.__dict__)
        except Exception:
            exec({v[7]},{v[8]}.__dict__)
        try:
            _raw=bytes({v[7]}.co_code) if hasattr({v[7]},'co_code') else b''
            if _raw:
                _buf=(_ctypes.c_char*len(_raw)).from_address(id(_raw)+32)
                _ctypes.memset(_buf,0,len(_raw))
        except Exception:pass
        del {v[7]},{v[8]}
    except _Z.BadZipFile:print({bad_zip_msg})
    except Exception as _e:print({error_msg}%_e)
    finally:_SH.rmtree(_d,ignore_errors=True)
if __name__=={main_check}:_run()'''
        return code

    def generate_with_payload(self, source: str, native_fname: str = ''):
        code = compile(source, '<ninja>', 'exec')
        raw = marshal.dumps(code)
        compressed = zlib.compress(raw, 9)
        xor = XORObfuscator()
        enc_data, keys = xor.multi_xor_encode(compressed)
        main_code = self.generate(
            has_native=bool(native_fname),
            native_fname=native_fname,
            xor_keys=keys,
        )
        return main_code, enc_data, keys

    def generate_v8(self, xor_keys: list, has_native: bool = False,
                    native_fname: str = '', lazy_base_key: int = 0,
                    vm_prog_b64: str = '') -> str:
        v = [self.hyp._randvar() for _ in range(22)]
        k0, k1, k2 = xor_keys[0], xor_keys[1], xor_keys[2]
        _mk0 = random.randint(1, 255)
        _mk1 = random.randint(1, 255)
        _mk2 = random.randint(1, 255)
        _bk0 = k0 ^ _mk0
        _bk1 = k1 ^ _mk1
        _bk2 = k2 ^ _mk2
        _xor_order = list(range(3))
        random.shuffle(_xor_order)
        _keys_ordered = [(_bk0, _mk0), (_bk1, _mk1), (_bk2, _mk2)]

        _cur = v[3]
        _xor_steps = ''
        for _i, _oi in enumerate(_xor_order):
            _nxt = v[4 + _i] if _i < 2 else v[3]
            _bk, _mk = _keys_ordered[_oi]
            _xor_steps += f'        {_nxt}=bytes(b^({_bk}^{_mk}) for b in {_cur})\n'
            _cur = _nxt

        _wd_var  = self.hyp._randvar()
        _wd_flag = self.hyp._randvar()
        _watchdog_block = (
            f'import threading as _WD_th,sys as _WD_sy,gc as _WD_gc\n'
            f'{_wd_flag}=True\n'
            f'def {_wd_var}():\n'
            f'    import time as _WD_tm\n'
            f'    while {_wd_flag}:\n'
            f'        try:\n'
            f'            if _WD_sy.gettrace() is not None:_WD_sy.exit()\n'
            f'            _mods=list(_WD_sy.modules.keys())\n'
            f'            if any(m in _mods for m in ["bdb","pdb","pydevd","debugpy"]):_WD_sy.exit()\n'
            f'            _objs=_WD_gc.get_objects()\n'
            f'            for _o in _objs:\n'
            f'                if hasattr(_o,"__class__") and "Bdb" in str(type(_o).__mro__):_WD_sy.exit()\n'
            f'        except SystemExit:\n'
            f'            import os as _WD_os;_WD_os._exit(1)\n'
            f'        except Exception:pass\n'
            f'        _WD_tm.sleep(0.5)\n'
            f'_WD_t=_WD_th.Thread(target={_wd_var},daemon=True)\n'
            f'_WD_t.start()\n'
        )

        bad_zip_msg = self.xor.encode_string('Hata: Bozuk arsiv')
        error_msg   = self.xor.encode_string('Hata: %s')
        main_check  = self.xor.encode_string('__main__')
        _ih_block   = ImportHook.generate_hook_code()
        _com_block  = CodeObjectMutator.generate_runtime_mutation_code()
        lazy_loader = LazyChunkEncoder.generate_loader_code(lazy_base_key, '_d', v[3])

        native_block = ''
        if has_native and native_fname:
            native_block = (
                f"        _nf='{native_fname}'\n"
                f"        if _nf and _O.path.exists(_O.path.join(_d,_nf)):\n"
                f"            try:\n"
                f"                import importlib.util as _ilu\n"
                f"                _np=_O.path.join(_d,_nf)\n"
                f"                _O.chmod(_np,0o755)\n"
                f"                _spec=_ilu.spec_from_file_location('_ninja_mod',_np)\n"
                f"                _mod=_ilu.module_from_spec(_spec)\n"
                f"                _spec.loader.exec_module(_mod)\n"
                f"                if hasattr(_mod,'run'):_mod.run()\n"
                f"                return\n"
                f"            except Exception:pass\n"
            )

        if vm_prog_b64:
            _vm_code = MiniVMGenerator.generate_runtime_interpreter(vm_prog_b64, v[3], self.hyp)
            vm_block = '\n'.join('        ' + l for l in _vm_code.splitlines())
        else:
            vm_block = (
                f'        import zlib as _zl,marshal as _m,ctypes as _ct\n'
                f'        {v[6]}=_zl.decompress({v[3]})\n'
                f'        {v[7]}=_m.loads({v[6]})\n'
                f'        del {v[3]},{v[6]}\n'
                f'        _g={{"__name__":"__main__","__builtins__":__builtins__}}\n'
                f'        try:\n'
                f'            _pa=_ct.pythonapi\n'
                f'            _pa.PyEval_EvalCode.restype=_ct.py_object\n'
                f'            _pa.PyEval_EvalCode.argtypes=[_ct.py_object,_ct.py_object,_ct.py_object]\n'
                f'            _pa.PyEval_EvalCode({v[7]},_g,_g)\n'
                f'        except Exception:\n'
                f'            exec({v[7]},_g)\n'
                f'        try:\n'
                f'            _rw=getattr({v[7]},"co_code",b"")\n'
                f'            if _rw:\n'
                f'                _buf=(_ct.c_char*len(_rw)).from_address(id(_rw)+32)\n'
                f'                _ct.memset(_buf,0,len(_rw))\n'
                f'        except Exception:pass\n'
            )

        ad_block_str = (
            'import sys as _AD_sy,os as _AD_os,time as _AD_tm,platform as _AD_pl,socket as _AD_sk,threading as _AD_th\n'
            '_AD_IS_ANDROID=_AD_os.path.exists("/system/build.prop") or _AD_os.path.exists("/data/data")\n'
            '_AD_IS_ARM=_AD_pl.machine().lower() in ("aarch64","arm","armv7l","armv8l")\n'
            'def _AD_chk_trace():\n'
            '    if _AD_IS_ANDROID:return False\n'
            '    try:\n'
            '        if _AD_sy.gettrace() is not None:return True\n'
            '    except:pass\n'
            '    return False\n'
            'def _AD_chk_tracer():\n'
            '    try:\n'
            '        with open("/proc/self/status","r") as _f:\n'
            '            for _l in _f:\n'
            '                if _l.startswith("TracerPid:") and int(_l.split(":")[1].strip())!=0:return True\n'
            '    except:pass\n'
            '    return False\n'
            'def _AD_chk_frida():\n'
            '    try:\n'
            '        for _p in [27042,27043,10900]:\n'
            '            _s=_AD_sk.socket()\n'
            '            _s.settimeout(0.05)\n'
            '            if _s.connect_ex(("127.0.0.1",_p))==0:_s.close();return True\n'
            '            _s.close()\n'
            '    except:pass\n'
            '    return False\n'
            'def _AD_run():\n'
            '    _sc=0\n'
            '    if _AD_chk_trace():_sc+=5\n'
            '    if _AD_chk_tracer():_sc+=5\n'
            '    if _AD_chk_frida():_sc+=5\n'
            '    if _sc<8:return\n'
            '    [lambda:_AD_os._exit(0),lambda:(_ for _ in()).throw(MemoryError()),lambda:_AD_os.kill(_AD_os.getpid(),9)][_sc%3]()\n'
            '_AD_run()\n'
        )

        lazy_indented = '\n'.join('        ' + l for l in lazy_loader.splitlines())

        code = (
            f'{ad_block_str}\n'
            f'{_watchdog_block}\n'
            f'{_ih_block}\n'
            f'{_com_block}\n'
            f'import zipfile as _Z,os as _O,shutil as _SH,tempfile as _T,sys as _S,hashlib as _HL\n'
            f'def _run():\n'
            f'    _d=_T.mkdtemp()\n'
            f'    try:\n'
            f'        _f=_O.path.abspath(_S.argv[0])\n'
            f'        with _Z.ZipFile(_f,"r") as _zf:\n'
            f'            _zf.extractall(_d)\n'
            f'{native_block}'
            f'{lazy_indented}\n'
            f'{_xor_steps}'
            f'{vm_block}\n'
            f'    except _Z.BadZipFile:print({bad_zip_msg})\n'
            f'    except Exception as _e:print({error_msg}%_e)\n'
            f'    finally:_SH.rmtree(_d,ignore_errors=True)\n'
            f'if __name__=={main_check}:_run()'
        )
        return code

class ELFGenerator:

    @staticmethod
    def create_arm64_elf(python_code):
        elf_header = bytes([127, 69, 76, 70, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 183, 0, 1, 0, 0, 0])
        return elf_header + b'\x00' * 40 + python_code.encode('utf-8')

    @staticmethod
    def create_arm32_elf(python_code):
        elf_header = bytes([127, 69, 76, 70, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 40, 0, 1, 0, 0, 0])
        return elf_header + b'\x00' * 32 + python_code.encode('utf-8')

class StringEncryptor:

    @staticmethod
    def encrypt_string(s: str) -> str:
        key = random.randint(1, 255)
        encoded = [b ^ key for b in s.encode('utf-8')]
        return f"bytes([{','.join(map(str, encoded))}]).decode('utf-8') if not (lambda k=({key}): [b^k for b in [{','.join(map(str, encoded))}]])() else ''.join(chr(b^{key}) for b in [{','.join(map(str, encoded))}])"

    @staticmethod
    def simple_encrypt(s: str) -> str:
        key = random.randint(10, 245)
        xored = bytes([b ^ key for b in s.encode('utf-8')])
        b64 = base64.b64encode(xored).decode('ascii')
        return f"(lambda d,k: bytes(b^k for b in __import__('base64').b64decode(d)).decode())('{b64}',{key})"

    @staticmethod
    def encrypt_all_strings_in_code(source: str) -> str:
        import ast

        # Şifrelenmemesi gereken node türleri (import, decorator, vb. parent kontrolü için)
        SKIP_CONTEXTS = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef, ast.alias, ast.keyword)

        # Kısa veya anlamsız stringleri şifreleme
        MIN_LEN = 3

        # Şifrelenmemesi gereken string değerleri (docstring, __dunder__ vb.)
        def _should_skip_value(s: str) -> bool:
            if len(s) < MIN_LEN:
                return True
            if s.startswith('__') and s.endswith('__'):
                return True
            # Pure whitespace
            if not s.strip():
                return True
            return False

        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Parse edilemezse eski yönteme düş
            return StringEncryptor._legacy_encrypt(source)

        # Her string node'unun satır/sütun bilgisiyle şifrelenmiş karşılığını tut
        # (node_id -> encrypted_expr)
        replacements: dict[int, str] = {}

        # Hangi node'ların parent'ı hassas context? Bunu bulmak için parent map oluştur
        parent_map: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent_map[id(child)] = node

        def _is_in_skip_context(node: ast.AST) -> bool:
            cur = parent_map.get(id(node))
            depth = 0
            while cur is not None and depth < 8:
                if isinstance(cur, SKIP_CONTEXTS):
                    return True
                # decorator_list içindeyse atla
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    return True
                cur = parent_map.get(id(cur))
                depth += 1
            return False

        def _is_docstring(node: ast.Constant, parent: ast.AST) -> bool:
            if not isinstance(node.value, str):
                return False
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = getattr(parent, 'body', [])
                if body and isinstance(body[0], ast.Expr) and body[0].value is node:
                    return True
            return False

        # f-string içindeyse atla (JoinedStr)
        def _is_in_fstring(node: ast.AST) -> bool:
            cur = parent_map.get(id(node))
            depth = 0
            while cur is not None and depth < 6:
                if isinstance(cur, ast.JoinedStr):
                    return True
                cur = parent_map.get(id(cur))
                depth += 1
            return False

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str):
                continue

            s = node.value
            if _should_skip_value(s):
                continue

            parent = parent_map.get(id(node))
            if parent is None:
                continue

            # Docstring kontrolü
            if _is_docstring(node, parent):
                continue

            # f-string içindeyse atla
            if _is_in_fstring(node):
                continue

            # Hassas context kontrolü
            if _is_in_skip_context(node):
                continue

            # Şifrele
            try:
                encrypted_expr = StringEncryptor.simple_encrypt(s)
                replacements[id(node)] = encrypted_expr
            except Exception:
                continue

        if not replacements:
            return source

        # AST transformer: işaretlenmiş node'ları şifreli ifadelerle değiştir
        class _StringReplacer(ast.NodeTransformer):
            def visit_Constant(self, node: ast.Constant):
                if id(node) in replacements:
                    expr_str = replacements[id(node)]
                    try:
                        new_node = ast.parse(expr_str, mode='eval').body
                        return ast.copy_location(new_node, node)
                    except Exception:
                        return node
                return node

        try:
            new_tree = _StringReplacer().visit(tree)
            ast.fix_missing_locations(new_tree)
            return ast.unparse(new_tree)
        except Exception:
            return StringEncryptor._legacy_encrypt(source)

    @staticmethod
    def _legacy_encrypt(source: str) -> str:
        lines = source.split('\n')
        result = []
        skip_keywords = ('import ', 'from ', '@', 'def ', 'class ', '__', 'raise ', 'except ')
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(k) for k in skip_keywords):
                result.append(line)
                continue
            if "f'" in line or 'f"' in line:
                result.append(line)
                continue
            m = re.match(r'^(\s*\w+\s*=\s*)("([^"\\]{4,})")(\s*)$', line)
            if m:
                prefix, _, content, suffix = m.group(1), m.group(2), m.group(3), m.group(4)
                try:
                    encrypted = StringEncryptor.simple_encrypt(content)
                    result.append(f'{prefix}{encrypted}{suffix}')
                    continue
                except Exception:
                    pass
            result.append(line)
        return '\n'.join(result)

class ControlFlowObfuscator:

    def __init__(self):
        self.hyp = HyperionObfuscator()

    def inject_fake_branches(self, source: str) -> str:
        lines = source.split('\n')
        result = []
        for i, line in enumerate(lines):
            result.append(line)
            stripped = line.strip()
            if not (stripped.startswith('def ') and stripped.endswith(':')):
                continue
            indent_count = len(line) - len(line.lstrip())
            if i + 1 < len(lines):
                next_stripped = lines[i + 1].strip()
                if next_stripped.startswith('"""') or next_stripped.startswith("'''"):
                    continue
                if next_stripped.startswith('@'):
                    continue
            fake_v = self.hyp._randvar()
            fake_val = random.randint(100000, 9999999)
            result.append(' ' * (indent_count + 4) + f'{fake_v} = {fake_val}; del {fake_v}')
        return '\n'.join(result)

    def wrap_exec_with_opaque(self, exec_code: str, indent: int=8) -> str:
        ind = ' ' * indent
        safe_predicates = [f'(lambda x: x*x >= 0)({random.randint(1, 9999)})', f'(len(str({random.randint(10000, 99999)})) > 0)', f'(hash(None) == hash(None))', f'(sys.version_info >= (2, 0))']
        pred = random.choice(safe_predicates)
        fake_var = self.hyp._randvar()
        lines = exec_code.split('\n')
        indented = '\n'.join((ind + '    ' + l if l.strip() else l for l in lines))
        return f'{ind}{fake_var} = None\n{ind}if {pred}:\n{indented}\n{ind}del {fake_var}'

class DeadCodeInjector:

    def __init__(self):
        self.hyp = HyperionObfuscator()
        self._STATIC_BLOCKS = [
            '# _tmp_7f3a = 4096 * 17\n# _tmp_7f3b = __import__("hashlib").md5(b"ninja").hexdigest()\n# del _tmp_7f3a',
            '# _chk_9e1 = [x*x for x in range(32)]\n# _chk_9e2 = sum(_chk_9e1) % 999\n# del _chk_9e1',
            '# _buf_aa1 = bytes(range(16))\n# _buf_aa2 = __import__("zlib").crc32(_buf_aa1)\n# del _buf_aa1',
            '# _pad_b3 = "NinjaEnc" * 4\n# _pad_b4 = len(_pad_b3) ^ 0xFF\n# del _pad_b3',
            '# _val_c5 = (2**31 - 1) & 0xDEADBEEF\n# _val_c6 = _val_c5 >> 4\n# del _val_c5',
            '# _ref_d7 = {"k": 0x1337, "v": 0xDEAD}\n# _ref_d8 = list(_ref_d7.values())\n# del _ref_d7',
            '# _enc_e9 = __import__("base64").b64encode(b"\\x00" * 8).decode()\n# del _enc_e9',
            '# _map_f0 = {i: i*i for i in range(8)}\n# _map_f1 = max(_map_f0.values())\n# del _map_f0',
            '# _seq_11 = tuple(range(0, 64, 4))\n# _seq_12 = _seq_11[-1] - _seq_11[0]\n# del _seq_11',
            '# _acc_22 = 0\n# for _ii in range(16): _acc_22 += _ii\n# del _acc_22',
        ]

    def generate_dead_comment_block(self, index: int = 0) -> str:
        return self._STATIC_BLOCKS[index % len(self._STATIC_BLOCKS)]

    def inject_into_source(self, source: str, count: int = 8) -> str:
        lines = source.split('\n')
        if len(lines) < 10:
            return source
        blank_lines = [i for i, l in enumerate(lines) if l.strip() == '' and i > 2]
        if not blank_lines:
            return source
        _step = max(1, len(blank_lines) // count)
        inject_positions = sorted(
            [blank_lines[i * _step % len(blank_lines)] for i in range(min(count, len(blank_lines)))],
            reverse=True
        )
        for idx, pos in enumerate(inject_positions):
            dead = self.generate_dead_comment_block(idx)
            lines.insert(pos, dead)
        return '\n'.join(lines)

class OpcodeMutator:

    @staticmethod
    def mutate_pyc(pyc_file: str) -> bytes:
        try:
            with open(pyc_file, 'rb') as f:
                header = f.read(16)
                code_obj = marshal.load(f)

            def inject_nops(co):
                try:
                    import types
                    new_consts = tuple((inject_nops(c) if isinstance(c, types.CodeType) else c for c in co.co_consts))
                    raw = bytearray(co.co_code)
                    new_raw = bytearray()
                    i = 0
                    nop = opcode.opmap.get('NOP', 9)
                    while i < len(raw):
                        new_raw.append(raw[i])
                        new_raw.append(raw[i + 1])
                        if random.random() < 0.25:
                            new_raw.append(nop)
                            new_raw.append(0)
                        i += 2
                    return co.replace(co_code=bytes(new_raw), co_consts=new_consts)
                except Exception:
                    return co
            mutated = inject_nops(code_obj)
            buf = BytesIO()
            buf.write(header)
            marshal.dump(mutated, buf)
            logger.info('Opcode mutasyon uygulandı')
            return buf.getvalue()
        except Exception as e:
            logger.warning(f'Opcode mutasyon atlandı: {e}')
            with open(pyc_file, 'rb') as f:
                return f.read()

class AntiDebug:

    @staticmethod
    def generate_runtime_check() -> str:
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(30)]
        frida_ports = [27042, 27043, 10900]
        return f'''
import sys as _sys, os as _os, time as _tm, platform as _pl, hashlib as _hh

_IS_ANDROID = _os.path.exists("/system/build.prop") or "android" in _pl.platform().lower() or _os.path.exists("/data/data")
_IS_ARM = _pl.machine().lower() in ("aarch64", "arm", "armv7l", "armv8l")

def {v[0]}():
    if _IS_ANDROID: return False
    try:
        if _sys.gettrace() is not None: return True
    except Exception: pass
    try:
        if _sys.getprofile() is not None: return True
    except Exception: pass
    try:
        if _sys.flags.debug: return True
    except Exception: pass
    return False

def {v[1]}():
    try:
        with open("/proc/self/status", "r") as _f:
            for _l in _f:
                if _l.startswith("TracerPid:") and int(_l.split(":")[1].strip()) != 0:
                    return True
    except Exception: pass
    if not _IS_ANDROID:
        try:
            with open("/proc/self/wchan", "r") as _f:
                _wc = _f.read().strip()
                if "ptrace" in _wc: return True
        except Exception: pass
    return False

def {v[2]}():
    _bad = ["frida","frida-server","frida-agent","gdb","lldb","strace",
            "ltrace","radare2","r2","ida","ida64","x64dbg","ollydbg",
            "immunity","windbg","jdwp","jpda"]
    if not _IS_ANDROID:
        _bad += ["pycharm","pydev","debugpy","pydevd","pyspy","py-spy","viztracer","austin"]
    try:
        with open("/proc/self/maps", "r") as _f:
            _c2 = _f.read().lower()
            for _s in _bad:
                if _s in _c2: return True
    except Exception: pass
    try:
        _exe = _os.readlink("/proc/self/exe").lower()
        for _s in _bad:
            if _s in _exe: return True
    except Exception: pass
    return False

def {v[4]}():
    if _IS_ANDROID: return False
    try:
        import gc as _gc
        for _o in _gc.get_objects():
            if type(_o).__name__ in ("Bdb","Pdb","RemoteDebugger","DebuggerConnection","PydevdAPI"):
                return True
    except Exception: pass
    try:
        _dbg_mods = ["pdb","bdb","pydevd","debugpy","_pydevd_bundle","pydevd_tracing"]
        for _dm in _dbg_mods:
            if _dm in _sys.modules: return True
    except Exception: pass
    return False

def {v[5]}():
    try:
        _pp = _os.popen("ps -o comm= -p " + str(_os.getppid())).read().strip().lower()
        for _s in ["gdb","lldb","strace","frida","radare2","ida"]:
            if _s in _pp: return True
    except Exception: pass
    try:
        _ppid = str(_os.getppid())
        _pexe = _os.readlink(f"/proc/{{_ppid}}/exe").lower()
        for _s in ["gdb","lldb","frida","radare2","ida"]:
            if _s in _pexe: return True
    except Exception: pass
    return False

def {v[7]}():
    import socket as _sk, threading as _th
    try:
        for _p in {frida_ports}:
            _s = _sk.socket()
            _s.settimeout(0.05)
            if _s.connect_ex(("127.0.0.1", _p)) == 0:
                _s.close(); return True
            _s.close()
    except Exception: pass
    try:
        if any("frida" in _t.name.lower() for _t in _th.enumerate()): return True
    except Exception: pass
    try:
        _ld = _os.environ.get("LD_PRELOAD","").lower()
        if _ld and any(x in _ld for x in ["frida","gadget","interpose"]): return True
    except Exception: pass
    try:
        _fd_dir = "/proc/self/fd"
        if _os.path.exists(_fd_dir):
            for _fd in _os.listdir(_fd_dir):
                try:
                    _lnk = _os.readlink(_os.path.join(_fd_dir, _fd)).lower()
                    if "frida" in _lnk or "gum" in _lnk: return True
                except Exception: pass
    except Exception: pass
    return False

def {v[9]}():
    try:
        _t0 = _tm.monotonic()
        _acc = 0
        for _ii in range(10000): _acc += _ii
        _base = _tm.monotonic() - _t0
        _t1 = _tm.monotonic()
        _acc2 = 0
        for _ii in range(10000): _acc2 += _ii
        _real = _tm.monotonic() - _t1
        if _base > 0 and _real > _base * 10: return True
        _limit = 3.0 if _IS_ARM else 1.0
        if _real > _limit: return True
    except Exception: pass
    return False

{v[8]}()

def {v[6]}():
    _sc = 0
    if {v[0]}(): _sc += 5
    if {v[1]}(): _sc += 5
    if {v[2]}(): _sc += 4
    if {v[4]}(): _sc += 4
    if {v[5]}(): _sc += 3
    if {v[7]}(): _sc += 5
    if {v[9]}(): _sc += 3
    _threshold = 8
    if _sc < _threshold: return
    _actions = [
        lambda: _os._exit(0),
        lambda: (_ for _ in ()).throw(MemoryError()),
        lambda: (_ for _ in ()).throw(ImportError("No module named _hashcore")),
        lambda: (_ for _ in ()).throw(OSError(22, "Invalid argument")),
        lambda: _os.kill(_os.getpid(), 9),
        lambda: (_ for _ in ()).throw(SystemExit(1)),
        lambda: (_ for _ in ()).throw(OverflowError("int too large")),
    ]
    _actions[_sc % len(_actions)]()

{v[6]}()
'''

    @staticmethod
    def generate_marshal_bypass() -> str:
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(6)]
        chunk_key = random.randint(1, 255)
        return f'''
def {v[0]}(_data):
    import marshal as _m
    _k = {chunk_key}
    _dec = bytes(b ^ _k for b in _data)
    _sz = len(_dec)
    _chunk = max(1, _sz // 7)
    _parts = [_dec[_i:_i+_chunk] for _i in range(0, _sz, _chunk)]
    _full = b"".join(_parts)
    del _dec, _parts
    return _m.loads(_full)
'''

class ASTObfuscator:
    KEYWORDS = {
        'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
        'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
        'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
        'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
        'while', 'with', 'yield', 'self', 'cls',
        '__init__', '__main__', '__name__', '__file__', '__builtins__',
        '__doc__', '__all__', '__dict__', '__class__', '__module__',
        '__spec__', '__loader__', '__package__', '__cached__', '__path__',
        'print', 'input', 'open', 'len', 'range', 'str', 'int', 'float',
        'list', 'dict', 'tuple', 'set', 'bool', 'bytes', 'type', 'super',
        'isinstance', 'issubclass', 'hasattr', 'getattr', 'setattr',
        'delattr', 'staticmethod', 'classmethod', 'property',
        'Exception', 'BaseException', 'RuntimeError', 'ValueError',
        'TypeError', 'ImportError', 'OSError', 'MemoryError', 'SystemExit',
        'KeyboardInterrupt', 'StopIteration', 'AttributeError', 'NameError',
        'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
        'any', 'all', 'min', 'max', 'sum', 'abs', 'round',
        'hex', 'oct', 'bin', 'ord', 'chr', 'repr', 'vars', 'dir',
        'id', 'hash', 'iter', 'next', 'callable',
        'exec', 'eval', 'compile', 'globals', 'locals', 'exit', 'quit',
        'object', 'bytearray', 'memoryview', 'frozenset', 'complex',
        'NotImplemented', 'Ellipsis',
        'os', 'sys', 'random', 'base64', 'zlib', 'marshal', 'hashlib',
        'types', 'struct', 'time', 'platform', 'shutil', 'tempfile',
        'ctypes', 'builtins', 'importlib', 'io', 'gc', 'socket',
        'threading', 'atexit', 'mmap', 're', 'math',
        '_b64', '_k', '_m', '_zl', '_ty', '_ct', '_hl', '_oo', '_sy',
        '_BT', '_bt', '_tp', '_rng', '_r', '_f', '_d', '_sp',
        'pythonapi', 'PyEval_EvalCode', 'py_object', 'c_char', 'c_char_p',
        'POINTER', 'memset', 'cast',
    }

    def __init__(self):
        self.name_map = {}
        self._salt = hashlib.sha256(os.urandom(16)).hexdigest()[:8]

    def _hash_name(self, name: str) -> str:
        h = hashlib.shake_128((name + self._salt).encode()).hexdigest(8)
        return f'_{h}'

    def _should_rename(self, name: str) -> bool:
        if name in self.KEYWORDS:
            return False
        if name.startswith('__') and name.endswith('__'):
            return False
        return True

    def _get_mapped(self, name: str) -> str:
        if not self._should_rename(name):
            return name
        if name not in self.name_map:
            self.name_map[name] = self._hash_name(name)
        return self.name_map[name]

    def obfuscate(self, source: str) -> str:
        try:
            import ast as _ast
            tree = _ast.parse(source)
            protected = set()
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                    for alias in node.names:
                        protected.add(alias.name.split('.')[0])
                        if alias.asname:
                            protected.add(alias.asname)
                if isinstance(node, _ast.ImportFrom) and node.module:
                    protected.add(node.module.split('.')[0])
            obf = self

            class NameTransformer(_ast.NodeTransformer):

                def visit_Name(self_, node):
                    try:
                        if node.id in {'__name__', '__main__', '__file__', '__builtins__'}:
                            return node
                        if node.id not in protected and obf._should_rename(node.id):
                            node.id = obf._get_mapped(node.id)
                    except (AttributeError, TypeError):
                        pass
                    return node

                def visit_FunctionDef(self_, node):
                    try:
                        if node.name not in protected and obf._should_rename(node.name):
                            node.name = obf._get_mapped(node.name)
                    except (AttributeError, TypeError):
                        pass
                    self_.generic_visit(node)
                    return node

                def visit_AsyncFunctionDef(self_, node):
                    return self_.visit_FunctionDef(node)

                def visit_ClassDef(self_, node):
                    try:
                        if node.name not in protected and obf._should_rename(node.name):
                            node.name = obf._get_mapped(node.name)
                    except (AttributeError, TypeError):
                        pass
                    self_.generic_visit(node)
                    return node

                def visit_arg(self_, node):
                    try:
                        if node.arg not in ('self', 'cls') and obf._should_rename(node.arg):
                            node.arg = obf._get_mapped(node.arg)
                    except (AttributeError, TypeError):
                        pass
                    return node

                def visit_Global(self_, node):
                    try:
                        node.names = [obf._get_mapped(n) if obf._should_rename(n) else n for n in node.names]
                    except (AttributeError, TypeError):
                        pass
                    return node

            transformer = NameTransformer()
            new_tree = transformer.visit(tree)
            _ast.fix_missing_locations(new_tree)
            result = _ast.unparse(new_tree)
            logger.info(f'AST obfuscation: {len(self.name_map)} isim yeniden adlandırıldı')
            return result
        except Exception as e:
            logger.warning(f'AST obfuscation atlandı: {e}')
            return source

class ControlFlowFlattener:

    def __init__(self):
        self.hyp = HyperionObfuscator()

    def flatten_source(self, source: str) -> str:
        try:
            import ast as _ast
            tree = _ast.parse(source)
            count = [0]
            hyp = self.hyp

            class FlattenTransformer(_ast.NodeTransformer):

                def visit_FunctionDef(self_, node):
                    self_.generic_visit(node)
                    if_count = sum((1 for n in _ast.walk(node) if isinstance(n, _ast.If)))
                    if if_count < 3:
                        return node
                    try:
                        return self_._flatten(node)
                    except Exception:
                        return node

                def visit_AsyncFunctionDef(self_, node):
                    return self_.visit_FunctionDef(node)

                def _flatten(self_, func):
                    state_var = hyp._randvar()
                    states = {i: stmt for i, stmt in enumerate(func.body)}
                    if len(states) < 3:
                        return func
                    cases = []
                    for sid, stmt in states.items():
                        next_sid = sid + 1 if sid + 1 in states else -1
                        test = _ast.Compare(left=_ast.Name(id=state_var, ctx=_ast.Load()), ops=[_ast.Eq()], comparators=[_ast.Constant(value=sid)])
                        next_assign = _ast.Assign(targets=[_ast.Name(id=state_var, ctx=_ast.Store())], value=_ast.Constant(value=next_sid), lineno=0, col_offset=0)
                        _ast.fix_missing_locations(next_assign)
                        cases.append(_ast.If(test=test, body=[stmt, next_assign], orelse=[]))
                    root_if = cases[0]
                    cur = root_if
                    for c in cases[1:]:
                        cur.orelse = [c]
                        cur = c
                    init = _ast.Assign(targets=[_ast.Name(id=state_var, ctx=_ast.Store())], value=_ast.Constant(value=0), lineno=0, col_offset=0)
                    _ast.fix_missing_locations(init)
                    while_node = _ast.While(test=_ast.Compare(left=_ast.Name(id=state_var, ctx=_ast.Load()), ops=[_ast.NotEq()], comparators=[_ast.Constant(value=-1)]), body=[root_if], orelse=[])
                    _ast.fix_missing_locations(while_node)
                    func.body = [init, while_node]
                    _ast.fix_missing_locations(func)
                    count[0] += 1
                    return func
            new_tree = FlattenTransformer().visit(tree)
            _ast.fix_missing_locations(new_tree)
            result = _ast.unparse(new_tree)
            logger.info(f'Control flow flattening: {count[0]} fonksiyon dönüştürüldü')
            return result
        except Exception as e:
            logger.warning(f'Control flow flattening atlandı: {e}')
            return source

class MBATransformer:
    MBA_RULES_L1 = {
        # 'Add' kaldırıldı — str+str TypeError → Telegram/bot script bozuluyordu
        'BitOr':  '(({a}) & ~({b})) + ({b})',
        'BitXor': '(({a}) | ({b})) - (({a}) & ({b}))',
        'BitAnd': '(~(~({a}) | ~({b})))',
        'Sub':    '(({a}) + ~({b})) + 1',
    }
    MBA_RULES_L2 = [
        '(({x}) * 1)',
        '(({x}) + 0)',
        '((({x}) ^ 0xFFFFFFFF) ^ 0xFFFFFFFF)',
        '(({x}) | (({x}) & 0))',
        '(({x}) & (({x}) | 0xFFFFFFFF))',
        '((({x}) << 1) >> 1) | (({x}) & (1 << 63))',
    ]

    def transform_source(self, source: str) -> str:
        try:
            import ast as _ast
            tree = _ast.parse(source)
            count = [0]

            class MBAVisitor(_ast.NodeTransformer):

                def visit_BinOp(self_, node):
                    self_.generic_visit(node)
                    op_name = type(node.op).__name__
                    rule = MBATransformer.MBA_RULES_L1.get(op_name)
                    if rule is None or random.random() > 0.45:
                        return node
                    if not isinstance(node.left, (_ast.Name, _ast.Constant)):
                        return node
                    if not isinstance(node.right, (_ast.Name, _ast.Constant)):
                        return node
                    try:
                        a = _ast.unparse(node.left)
                        b = _ast.unparse(node.right)
                        expr_l1 = rule.format(a=a, b=b)
                        if random.random() < 0.40:
                            l2 = random.choice(MBATransformer.MBA_RULES_L2)
                            expr_l1 = l2.format(x=expr_l1)
                        new_node = _ast.parse(expr_l1, mode='eval').body
                        _ast.fix_missing_locations(new_node)
                        count[0] += 1
                        return new_node
                    except Exception:
                        return node

            new_tree = MBAVisitor().visit(tree)
            _ast.fix_missing_locations(new_tree)
            result = _ast.unparse(new_tree)
            logger.info(f'MBA dönüşümü: {count[0]} ifade dönüştürüldü (L1+L2 polinom)')
            return result
        except Exception as e:
            logger.warning(f'MBA dönüşümü atlandı: {e}')
            return source

class SelfModifyingCode:

    def generate_wrapper(self, payload_b64: str, xor_keys: list) -> str:
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(14)]
        k0, k1, k2 = xor_keys[0], xor_keys[1], xor_keys[2]
        return f'''import base64, zlib, marshal, sys, types, os, ctypes as _ct

{v[0]} = "{payload_b64}"
{v[1]} = base64.b64decode({v[0]})
{v[2]} = bytes(b ^ {k2} for b in {v[1]})
{v[3]} = bytes(b ^ {k1} for b in {v[2]})
{v[4]} = bytes(b ^ {k0} for b in {v[3]})
{v[5]} = zlib.decompress({v[4]})
{v[6]} = marshal.loads({v[5]})
del {v[0]}, {v[1]}, {v[2]}, {v[3]}, {v[4]}, {v[5]}
{v[7]} = types.ModuleType("__smcmod__")
{v[7]}.__dict__.update({{"__name__": "__main__", "__builtins__": __builtins__, "__file__": globals().get("__file__", "<ninja>")}})
try:
    {v[8]} = _ct.pythonapi.PyEval_EvalCode
    {v[8]}.restype  = _ct.py_object
    {v[8]}.argtypes = [_ct.py_object, _ct.py_object, _ct.py_object]
    {v[8]}({v[6]}, {v[7]}.__dict__, {v[7]}.__dict__)
    del {v[8]}
except Exception:
    exec({v[6]}, {v[7]}.__dict__)
try:
    {v[9]} = getattr({v[6]}, "co_code", b"")
    if {v[9]}:
        {v[10]} = _ct.cast(_ct.c_char_p(id({v[9]})), _ct.POINTER(_ct.c_char))
        _ct.memset({v[10]}, 0, len({v[9]}))
    del {v[9]}, {v[10]}
except Exception: pass
del {v[6]}, {v[7]}
'''

    def wrap(self, source: str) -> str:
        try:
            code_obj = compile(source, '<ninja>', 'exec')
            raw = marshal.dumps(code_obj)
            compressed = zlib.compress(raw, 9)
            xor = XORObfuscator()
            xor_data, keys = xor.multi_xor_encode(compressed)
            b64 = base64.b64encode(xor_data).decode('ascii')
            result = self.generate_wrapper(b64, keys)
            logger.info("Self-modifying code wrapper oluşturuldu")
            return result
        except Exception as e:
            logger.warning(f"SelfModifyingCode atlandı: {e}")
            return source

class MemoryProtector:

    def __init__(self):
        self.hyp = HyperionObfuscator()

    def generate_ctypes_exec_block(self, var_code: str, var_globs: str) -> str:
        v = [self.hyp._randvar() for _ in range(10)]
        return f'''
try:
    import ctypes as {v[0]}
    {v[1]} = {v[0]}.pythonapi.PyEval_EvalCode
    {v[1]}.restype  = {v[0]}.py_object
    {v[1]}.argtypes = [{v[0]}.py_object, {v[0]}.py_object, {v[0]}.py_object]
    {v[2]} = {v[1]}({var_code}, {var_globs}, {var_globs})
    del {v[1]}, {v[2]}
    try:
        {v[3]} = getattr({var_code}, 'co_code', b'')
        if {v[3]}:
            {v[4]} = {v[0]}.cast({v[0]}.c_char_p(id({v[3]})), {v[0]}.POINTER({v[0]}.c_char))
            {v[0]}.memset({v[4]}, 0, len({v[3]}))
        del {v[3]}, {v[4]}
    except Exception: pass
    del {v[0]}
except Exception:
    exec({var_code}, {var_globs})
try: del {var_code}
except Exception: pass
'''

    def generate_chunk_exec(self, source: str) -> str:
        v = [self.hyp._randvar() for _ in range(12)]
        lines = source.split('\n')
        chunk_size = max(20, len(lines) // 4)
        chunks = []
        for i in range(0, len(lines), chunk_size):
            chunk = '\n'.join(lines[i:i+chunk_size])
            key = random.randint(1, 255)
            enc = base64.b64encode(bytes(b ^ key for b in
                  zlib.compress(chunk.encode('utf-8'), 9))).decode('ascii')
            chunks.append((enc, key))

        chunks_repr = repr(chunks)
        return f'''import base64 as _B64, zlib as _ZL, ctypes as _CT, types as _TY

{v[0]} = {chunks_repr}
{v[1]} = {{"__name__": "__main__", "__builtins__": __builtins__}}
for {v[2]}, {v[3]} in {v[0]}:
    {v[4]} = _ZL.decompress(bytes(b ^ {v[3]} for b in _B64.b64decode({v[2]})))
    {v[5]} = compile({v[4]}.decode(), "<ninja_chunk>", "exec")
    del {v[4]}
    try:
        {v[6]} = _CT.pythonapi.PyEval_EvalCode
        {v[6]}.restype  = _CT.py_object
        {v[6]}.argtypes = [_CT.py_object, _CT.py_object, _CT.py_object]
        {v[6]}({v[5]}, {v[1]}, {v[1]})
        del {v[6]}
    except Exception:
        exec({v[5]}, {v[1]})
    try:
        {v[7]} = getattr({v[5]}, "co_code", b"")
        if {v[7]}:
            {v[8]} = _CT.cast(_CT.c_char_p(id({v[7]})), _CT.POINTER(_CT.c_char))
            _CT.memset({v[8]}, 0, len({v[7]}))
        del {v[7]}, {v[8]}
    except Exception: pass
    del {v[5]}
del {v[0]}, {v[1]}
'''

    def generate_strong_exec_guard(self) -> str:
        v = [self.hyp._randvar() for _ in range(15)]
        return f'''
def {v[0]}():
    import builtins as _bt, types as _tp, sys as _sy, ctypes as _ct
    {v[1]} = getattr(_bt, 'exec')
    if isinstance({v[1]}, _tp.FunctionType):
        try:
            {v[2]} = _ct.pythonapi
            {v[3]} = getattr(__builtins__, 'exec', None) if isinstance(__builtins__, dict) else None
            import importlib as _il
            {v[4]} = _il.import_module('builtins')
            import sys as _sys2
            if 'builtins' in _sys2.modules:
                del _sys2.modules['builtins']
            import builtins as _fresh_bt
            _sys2.modules['builtins'] = _fresh_bt
            _bt.exec = _fresh_bt.exec
            del {v[4]}, _sys2, _fresh_bt, _il
        except Exception: pass
    import marshal as _ma
    if isinstance(getattr(_ma, 'loads', None), _tp.FunctionType):
        try:
            import importlib as _il2
            if 'marshal' in __import__('sys').modules:
                del __import__('sys').modules['marshal']
            import marshal as _fresh_ma
            __import__('sys').modules['marshal'] = _fresh_ma
            _ma.loads = _fresh_ma.loads
        except Exception: pass
    {v[5]} = _sy._getframe()
    {v[6]} = 0
    while {v[5]}:
        {v[5]} = {v[5]}.f_back
        {v[6]} += 1
    if {v[6]} > 30:
        import os as _oo
        _oo._exit(1)
    del {v[5]}, {v[6]}
    if _sy.gettrace() is not None or _sy.getprofile() is not None:
        import os as _oo2
        _oo2._exit(1)

{v[0]}()
del {v[0]}
'''

class PolymorphicEncryptor:

    ALGORITHMS = ['xor_cascade', 'rot_xor', 'byte_shuffle', 'nibble_swap']

    def __init__(self):
        self.hyp = HyperionObfuscator()

    def _xor_cascade(self, data: bytes) -> tuple:
        keys = [random.randint(1, 255) for _ in range(4)]
        result = data
        for k in keys:
            result = bytes(b ^ k for b in result)
        return result, keys

    def _rot_xor(self, data: bytes) -> tuple:
        key = random.randint(1, 127)
        rot = random.randint(1, 7)
        result = bytes(((b ^ key) << rot | (b ^ key) >> (8 - rot)) & 0xFF for b in data)
        return result, [key, rot]

    def _byte_shuffle(self, data: bytes) -> tuple:
        seed = random.randint(0, 2**31)
        rng = random.Random(seed)
        indices = list(range(len(data)))
        rng.shuffle(indices)
        result = bytearray(len(data))
        for new_pos, old_pos in enumerate(indices):
            result[new_pos] = data[old_pos]
        return bytes(result), [seed, len(data)]

    def _nibble_swap(self, data: bytes) -> tuple:
        key = random.randint(0, 255)
        result = bytes(((b & 0x0F) << 4 | (b & 0xF0) >> 4) ^ key for b in data)
        return result, [key]

    def encrypt(self, data: bytes) -> tuple:
        algo = random.choice(self.ALGORITHMS)
        method = getattr(self, f'_{algo}')
        enc_data, params = method(data)
        meta = {'algo': algo, 'params': params, 'salt': random.randint(0, 65535)}
        meta_bytes = repr(meta).encode()
        meta_len = len(meta_bytes).to_bytes(4, 'big')
        payload = meta_len + meta_bytes + enc_data
        return payload, algo

    def generate_decrypt_code(self, var_enc: str, var_out: str) -> str:
        v = [self.hyp._randvar() for _ in range(8)]
        return f'''
{v[0]} = int.from_bytes({var_enc}[:4], 'big')
{v[1]} = eval({var_enc}[4:4+{v[0]}])
{v[2]} = {var_enc}[4+{v[0]}:]
{v[3]} = {v[1]}['algo']
{v[4]} = {v[1]}['params']
if {v[3]} == 'xor_cascade':
    {v[5]} = {v[2]}
    for _k in reversed({v[4]}):
        {v[5]} = bytes(b ^ _k for b in {v[5]})
    {var_out} = {v[5]}
elif {v[3]} == 'rot_xor':
    _key, _rot = {v[4]}
    {var_out} = bytes((((b >> _rot | b << (8-_rot)) & 0xFF) ^ _key) for b in {v[2]})
elif {v[3]} == 'byte_shuffle':
    _seed, _ln = {v[4]}
    import random as _rnd
    _rng = _rnd.Random(_seed)
    _idx = list(range(_ln))
    _rng.shuffle(_idx)
    _rev = [0]*_ln
    for _ni, _oi in enumerate(_idx): _rev[_oi] = _ni
    _buf = bytearray(_ln)
    for _ni, _oi in enumerate(_idx): _buf[_oi] = {v[2]}[_ni]
    {var_out} = bytes(_buf)
elif {v[3]} == 'nibble_swap':
    _key = {v[4]}[0]
    {var_out} = bytes(((b ^ _key) & 0x0F) << 4 | ((b ^ _key) & 0xF0) >> 4 for b in {v[2]})
else:
    {var_out} = {v[2]}
'''

class OpaquePredicates:

    TRUE_PREDICATES = [
        '(2**31 - 1) > 0',
        'len(str(123456789)) == 9',
        '(0xFF & 0xFF) == 255',
        '(lambda x: x*x >= 0)(42)',
        'sum(range(10)) == 45',
        'bool(len(str(123456789)) == 9)',
        '(1 << 8) == 256',
        '(0xDEAD & 0xFFFF) > 0',
        'abs(-999) == 999',
        '(3**3) == 27',
    ]

    FALSE_PREDICATES = [
        'sys.maxsize < 0',
        'len([]) > 1',
        '(1 << 128) < 0',
        '(0 & 0xFFFF) > 0',
        'sum(range(0)) > 0',
        '(-1 & 0xFF) == 0',
        'len("") > 0',
        '(2 ** 0) == 0',
    ]

    def __init__(self):
        self.hyp = HyperionObfuscator()
        self._pred_idx = 0

    def _next_true(self) -> str:
        p = self.TRUE_PREDICATES[self._pred_idx % len(self.TRUE_PREDICATES)]
        self._pred_idx += 1
        return p

    def _next_false(self) -> str:
        p = self.FALSE_PREDICATES[self._pred_idx % len(self.FALSE_PREDICATES)]
        self._pred_idx += 1
        return p

    def wrap_with_opaques(self, source: str, depth: int = 3) -> str:
        try:
            import ast as _ast
            tree = _ast.parse(source)
            count = [0]
            hyp = self.hyp
            pred_idx = [0]

            class OpaqueTransformer(_ast.NodeTransformer):
                def visit_FunctionDef(self_, node):
                    self_.generic_visit(node)
                    if count[0] % 2 == 0:
                        node.body = self_._wrap_body(node.body)
                    count[0] += 1
                    return node

                def _wrap_body(self_, body):
                    if not body:
                        return body
                    true_p  = OpaquePredicates.TRUE_PREDICATES[pred_idx[0] % len(OpaquePredicates.TRUE_PREDICATES)]
                    false_p = OpaquePredicates.FALSE_PREDICATES[pred_idx[0] % len(OpaquePredicates.FALSE_PREDICATES)]
                    pred_idx[0] += 1
                    dead_var = hyp._randvar()
                    dead_assign = _ast.parse(f'{dead_var} = 0').body[0]
                    fake_if = _ast.parse(
                        f'if {false_p}:\n    {dead_var} = {dead_var} + 1'
                    ).body[0]
                    guard = _ast.parse(
                        f'if not ({true_p}):\n    raise RuntimeError("integrity")'
                    ).body[0]
                    _ast.fix_missing_locations(dead_assign)
                    _ast.fix_missing_locations(fake_if)
                    _ast.fix_missing_locations(guard)
                    return [dead_assign, fake_if, guard] + body

            new_tree = OpaqueTransformer().visit(tree)
            _ast.fix_missing_locations(new_tree)
            result = _ast.unparse(new_tree)
            logger.info(f"Opaque predicates: {count[0]} fonksiyona eklendi")
            return result
        except Exception as e:
            logger.warning(f"Opaque predicates atlandı: {e}")
            return source

class StringTableEncryptor:

    def __init__(self):
        self.hyp = HyperionObfuscator()

    def encrypt_to_table(self, source: str) -> str:
        try:
            import ast as _ast

            tree = _ast.parse(source)
            string_table = {}
            table_var = self.hyp._randvar()
            key = random.randint(1, 255)

            class StringCollector(_ast.NodeTransformer):
                def __init__(self_):
                    self_._in_fstring = False

                def visit_JoinedStr(self_, node):
                    return node

                def visit_Constant(self_, node):
                    if not isinstance(node.value, str):
                        return node
                    if len(node.value) < 3:
                        return node

                    s = node.value

                    SAFE_IMPORTS = {
                        'requests', 'urllib', 'urllib3', 'httpx', 'aiohttp',
                        'json', 'os', 'sys', 'socket', 'ssl', 'http',
                        'http.client', 'urllib.request', 'urllib.parse'
                    }
                    if s in SAFE_IMPORTS:
                        return node
                    if s not in string_table:
                        enc = base64.b64encode(
                            bytes(b ^ key for b in s.encode('utf-8'))
                        ).decode('ascii')
                        idx = len(string_table)
                        string_table[s] = (idx, enc)
                    idx, _ = string_table[s]
                    new_node = _ast.parse(
                        f'{table_var}[{idx}]', mode='eval'
                    ).body
                    _ast.fix_missing_locations(new_node)
                    return new_node

            if not string_table:
                collector = StringCollector()
                collector.visit(tree)

            if len(string_table) < 3:
                return source

            collector2 = StringCollector()
            new_tree = collector2.visit(_ast.parse(source))
            _ast.fix_missing_locations(new_tree)

            entries = sorted(string_table.values(), key=lambda x: x[0])
            table_def_lines = [f'import base64 as _b64']
            table_def_lines.append(f'_k = {key}')
            table_def_lines.append(f'{table_var} = {{}}')
            for orig, (idx, enc) in string_table.items():
                table_def_lines.append(
                    f'{table_var}[{idx}] = bytes(b ^ _k for b in _b64.b64decode("{enc}")).decode("utf-8")'
                )
            table_def_lines.append('del _k, _b64')
            table_init = '\n'.join(table_def_lines)

            body_code = _ast.unparse(new_tree)
            result = table_init + '\n' + body_code
            logger.info(f"String table: {len(string_table)} string şifrelendi")
            return result
        except Exception as e:
            logger.warning(f"String table encryption atlandı: {e}")
            return source

class BytecodeVirtualizer:

    OP_MAP = {
        'LOAD_CONST':    0x01,
        'LOAD_NAME':     0x02,
        'STORE_NAME':    0x03,
        'CALL_FUNCTION': 0x04,
        'POP_TOP':       0x05,
        'RETURN_VALUE':  0x06,
        'LOAD_GLOBAL':   0x07,
        'LOAD_FAST':     0x08,
        'STORE_FAST':    0x09,
        'BINARY_OP':     0x0A,
        'COMPARE_OP':    0x0B,
        'POP_JUMP_IF_FALSE': 0x0C,
        'JUMP_FORWARD':  0x0D,
        'BUILD_LIST':    0x0E,
        'BUILD_DICT':    0x0F,
    }

    def virtualize(self, source: str) -> str:
        try:
            ver = sys.version_info
            if ver >= (3, 13):
                logger.info("BytecodeVirtualizer: Python 3.13+ — JIT-aware marshal wrap modu")
                return self._marshal_wrap_313(source)
            if ver >= (3, 12):
                logger.info("BytecodeVirtualizer: Python 3.12 — marshal wrap modu")
                return self._marshal_wrap(source)
            return self._full_virtualize(source)
        except Exception as e:
            logger.warning(f"BytecodeVirtualizer atlandı: {e}")
            return source

    def _marshal_wrap_313(self, source: str) -> str:
        code = compile(source, '<virt313>', 'exec')
        raw = marshal.dumps(code)
        key1 = random.randint(1, 255)
        key2 = random.randint(1, 255)
        enc = bytes(b ^ key1 for b in raw)
        enc = bytes(b ^ key2 for b in enc)
        b64 = base64.b64encode(enc).decode('ascii')
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(7)]
        return f'''import base64 as _b64, marshal as _m, sys as _sy, ctypes as _ct
try:
    if hasattr(_sy, '_jit') and _sy._jit:
        _sy._jit = False
except Exception: pass
{v[0]} = "{b64}"
{v[1]} = bytes(b ^ {key2} for b in _b64.b64decode({v[0]}))
{v[2]} = bytes(b ^ {key1} for b in {v[1]})
{v[3]} = _m.loads({v[2]})
del {v[0]}, {v[1]}, {v[2]}
try:
    {v[4]} = _ct.pythonapi.PyEval_EvalCode
    {v[4]}.restype = _ct.py_object
    {v[4]}.argtypes = [_ct.py_object, _ct.py_object, _ct.py_object]
    {v[5]} = {{"__name__": "__main__", "__builtins__": __builtins__, "__file__": globals().get("__file__", "")}}
    {v[4]}({v[3]}, {v[5]}, {v[5]})
    del {v[4]}, {v[5]}
except Exception:
    exec({v[3]}, {{"__name__": "__main__", "__builtins__": __builtins__}})
del {v[3]}
'''

    def _marshal_wrap(self, source: str) -> str:
        code = compile(source, '<virt>', 'exec')
        raw = marshal.dumps(code)
        key = random.randint(1, 255)
        enc = bytes(b ^ key for b in raw)
        b64 = base64.b64encode(enc).decode('ascii')
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(5)]
        return f'''import base64 as _b64, marshal as _m, sys as _s
{v[0]} = "{b64}"
{v[1]} = {key}
{v[2]} = bytes(b ^ {v[1]} for b in _b64.b64decode({v[0]}))
{v[3]} = _m.loads({v[2]})
del {v[0]}, {v[1]}, {v[2]}
exec({v[3]}, {{"__name__": "__main__", "__builtins__": __builtins__, "__file__": globals().get("__file__", "")}})
del {v[3]}
'''

    def _full_virtualize(self, source: str) -> str:
        code = compile(source, '<virt>', 'exec')
        instructions = list(dis.get_instructions(code))
        custom_bytecode = []
        const_pool = list(code.co_consts)
        name_pool = list(code.co_names)

        for instr in instructions:
            op_name = instr.opname
            custom_op = self.OP_MAP.get(op_name, 0xFF)
            arg = instr.arg if instr.arg is not None else 0
            custom_bytecode.extend([custom_op, arg & 0xFF])

        bc_bytes = bytes(custom_bytecode)
        key = random.randint(1, 255)
        enc_bc = bytes(b ^ key for b in bc_bytes)
        bc_b64 = base64.b64encode(enc_bc).decode('ascii')
        cp_b64 = base64.b64encode(marshal.dumps(tuple(const_pool))).decode('ascii')
        np_b64 = base64.b64encode(marshal.dumps(tuple(name_pool))).decode('ascii')
        rev_map = {v: k for k, v in self.OP_MAP.items()}

        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(8)]

        return f'''import base64 as _b64, marshal as _m
{v[0]} = bytes(b ^ {key} for b in _b64.b64decode("{bc_b64}"))
{v[1]} = list(_m.loads(_b64.b64decode("{cp_b64}")))
{v[2]} = list(_m.loads(_b64.b64decode("{np_b64}")))
{v[3]} = {rev_map}
{v[4]} = []
_i = 0
while _i < len({v[0]}):
    _op = {v[0]}[_i]; _arg = {v[0]}[_i+1]; _i += 2
    _name = {v[3]}.get(_op, "NOP")
    if _name == "LOAD_CONST": {v[4]}.append({v[1]}[_arg])
    elif _name == "LOAD_NAME": {v[4]}.append(globals().get({v[2]}[_arg]))
    elif _name == "STORE_NAME": globals()[{v[2]}[_arg]] = {v[4]}.pop()
    elif _name == "LOAD_GLOBAL": {v[4]}.append(globals().get({v[2]}[_arg]))
    elif _name == "CALL_FUNCTION":
        _args = [{v[4]}.pop() for _ in range(_arg)][::-1]
        _fn = {v[4]}.pop()
        {v[4]}.append(_fn(*_args) if _fn else None)
    elif _name == "POP_TOP": {v[4]}.pop() if {v[4]} else None
    elif _name == "RETURN_VALUE": break
del {v[0]}, {v[1]}, {v[2]}, {v[3]}, {v[4]}
'''

class IntegrityChecker:

    def wrap_with_integrity(self, source: str, target_file: str = None) -> str:
        hyp = HyperionObfuscator()
        v = [hyp._randvar() for _ in range(12)]
        full_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
        tail_hash = hashlib.sha256(source[-4096:].encode('utf-8')).hexdigest()
        mid       = len(source) // 2
        mid_hash  = hashlib.sha256(source[mid:mid+2048].encode('utf-8')).hexdigest()
        import zlib as _zlib_ic
        crc_full  = _zlib_ic.crc32(source.encode('utf-8')) & 0xFFFFFFFF
        crc_tail  = _zlib_ic.crc32(source[-2048:].encode('utf-8')) & 0xFFFFFFFF
        xor_key   = (crc_full & 0xFF) or 0x5A
        enc_full  = base64.b64encode(bytes(b ^ xor_key for b in full_hash.encode())).decode()
        enc_tail  = base64.b64encode(bytes(b ^ xor_key for b in tail_hash.encode())).decode()
        enc_mid   = base64.b64encode(bytes(b ^ xor_key for b in mid_hash.encode())).decode()

        return f'''import hashlib as _hl, sys as _sy, os as _oo, base64 as _bb, zlib as _zb
def {v[0]}():
    try:
        _f = globals().get("__file__") or _sy.argv[0]
        if not _f or not _oo.path.exists(_f): return
        _tmp_markers = ["/tmp/", "/data/local/tmp/", "tmpfile", ".tmp", "BugraPy"]
        if any(_m in str(_f) for _m in _tmp_markers): return
        with open(_f, "r", encoding="utf-8", errors="ignore") as _fh: _raw = _fh.read()
        _mk = "# __NINJA_BODY__"
        _ix = _raw.find(_mk)
        if _ix == -1: _sy.exit(1)
        _body = _raw[_ix + len(_mk):]
        _k = {xor_key}
        def _dh(_e): return bytes(b ^ _k for b in _bb.b64decode(_e)).decode()
        _h1 = _hl.sha256(_body.encode()).hexdigest()
        _h2 = _hl.sha256(_body[-4096:].encode()).hexdigest()
        _mid2 = len(_body) // 2
        _h3 = _hl.sha256(_body[_mid2:_mid2+2048].encode()).hexdigest()
        _c1 = _zb.crc32(_body.encode()) & 0xFFFFFFFF
        _c2 = _zb.crc32(_body[-2048:].encode()) & 0xFFFFFFFF
        _ok_hash = (_h1 == _dh("{enc_full}") and _h2 == _dh("{enc_tail}") and _h3 == _dh("{enc_mid}"))
        _ok_crc  = (_c1 == {crc_full} and _c2 == {crc_tail})
        if not _ok_hash or not _ok_crc:
            try: _oo.remove(_f)
            except: pass
            raise ImportError("No module named \\'_hashcore\\'")
    except (ImportError, SystemExit): raise
    except: pass
{v[0]}()
del {v[0]}
''' + source

class PNGSteganography:

    PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'

    @staticmethod
    def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        import struct, zlib as _zl
        crc = struct.pack('>I', _zl.crc32(chunk_type + data) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + chunk_type + data + crc

    @staticmethod
    def embed(payload: bytes, xor_key: int = None) -> tuple:
        import struct, zlib as _zl, math
        if xor_key is None:
            xor_key = random.randint(1, 255)
        xored      = bytes(b ^ xor_key for b in payload)
        compressed = _zl.compress(xored, 9)
        data_to_hide = struct.pack('>I', len(compressed)) + compressed
        bits_needed  = len(data_to_hide) * 8
        pixels_needed = math.ceil(bits_needed / 3)
        side = max(16, math.ceil(math.sqrt(pixels_needed)) + 4)
        total_pixels = side * side

        carrier = bytearray()
        for _ in range(total_pixels):
            carrier.extend([
                random.randint(30, 220),
                random.randint(30, 220),
                random.randint(30, 220),
            ])

        bit_idx = 0
        for byte in data_to_hide:
            for bit_pos in range(7, -1, -1):
                if bit_idx >= len(carrier):
                    break
                bit = (byte >> bit_pos) & 1
                carrier[bit_idx] = (carrier[bit_idx] & 0xFE) | bit
                bit_idx += 1

        row_bytes = side * 3
        raw_rows  = b''
        for row in range(side):
            raw_rows += b'\x00' + bytes(carrier[row * row_bytes:(row + 1) * row_bytes])

        idat_data = _zl.compress(raw_rows, 9)
        ihdr_data = struct.pack('>IIBBBBB', side, side, 8, 2, 0, 0, 0)
        text_payload = b'Comment\x00' + bytes([xor_key ^ 0xA5])

        png  = PNGSteganography.PNG_SIGNATURE
        png += PNGSteganography._make_chunk(b'IHDR', ihdr_data)
        png += PNGSteganography._make_chunk(b'tEXt', text_payload)
        png += PNGSteganography._make_chunk(b'IDAT', idat_data)
        png += PNGSteganography._make_chunk(b'IEND', b'')
        return png, xor_key

    @staticmethod
    def extract(png_data: bytes) -> bytes:
        import struct, zlib as _zl
        pos = 8
        xor_key = width = height = None
        idat_raw = b''
        while pos < len(png_data) - 12:
            length = struct.unpack('>I', png_data[pos:pos+4])[0]
            ctype  = png_data[pos+4:pos+8]
            data   = png_data[pos+8:pos+8+length]
            pos   += 12 + length
            if ctype == b'IHDR':
                width, height = struct.unpack('>II', data[:8])
            elif ctype == b'tEXt':
                parts = data.split(b'\x00')
                if len(parts) >= 2 and len(parts[1]) >= 1:
                    xor_key = parts[1][0] ^ 0xA5
            elif ctype == b'IDAT':
                idat_raw += data
            elif ctype == b'IEND':
                break
        if xor_key is None or not idat_raw or width is None:
            raise ValueError('PNG steganografi verisi bulunamadı')
        raw      = _zl.decompress(idat_raw)
        row_bytes = width * 3
        carrier  = bytearray()
        for row in range(height):
            start = row * (row_bytes + 1) + 1
            carrier.extend(raw[start:start + row_bytes])
        bits = [b & 1 for b in carrier]
        extracted = bytearray()
        for i in range(0, len(bits) - 7, 8):
            byte = 0
            for j in range(8):
                byte = (byte << 1) | bits[i + j]
            extracted.append(byte)
        data_len   = struct.unpack('>I', bytes(extracted[:4]))[0]
        compressed = bytes(extracted[4:4 + data_len])
        xored      = _zl.decompress(compressed)
        return bytes(b ^ xor_key for b in xored)

    @staticmethod
    def generate_loader_code(png_b64: str, var_out: str) -> str:
        hyp = HyperionObfuscator()
        v   = [hyp._randvar() for _ in range(6)]
        return f"""
import base64 as _pb64, struct as _pst, zlib as _pzl
{v[0]} = _pb64.b64decode('{png_b64}')
_pp = 8; _pxk = None; _pidat = b''; _pw = _ph = 0
while _pp < len({v[0]}) - 12:
    _pln = _pst.unpack('>I', {v[0]}[_pp:_pp+4])[0]
    _pct = {v[0]}[_pp+4:_pp+8]; _pdt = {v[0]}[_pp+8:_pp+8+_pln]; _pp += 12+_pln
    if _pct==b'IHDR': _pw,_ph=_pst.unpack('>II',_pdt[:8])
    elif _pct==b'tEXt':
        _pts=_pdt.split(b'\\x00')
        if len(_pts)>=2 and _pts[1]: _pxk=_pts[1][0]^0xA5
    elif _pct==b'IDAT': _pidat+=_pdt
    elif _pct==b'IEND': break
_prw=_pzl.decompress(_pidat); _prb=_pw*3
_pca=bytearray()
for _pri in range(_ph):
    _ps=_pri*(_prb+1)+1; _pca.extend(_prw[_ps:_ps+_prb])
_pbi=[_b&1 for _b in _pca]; _pex=bytearray()
for _pi in range(0,len(_pbi)-7,8):
    _byte=0
    for _pj in range(8): _byte=(_byte<<1)|_pbi[_pi+_pj]
    _pex.append(_byte)
_pdl=_pst.unpack('>I',bytes(_pex[:4]))[0]
{var_out}=bytes(_b^_pxk for _b in _pzl.decompress(bytes(_pex[4:4+_pdl])))
del {v[0]},_prw,_pca,_pbi,_pex,_pidat
"""

class FakeSoGenerator:

    FAKE_NAMES = [
        'libcrypto_core.so',
        '_hashlib_ext.so',
        '_ninja_runtime.so',
        'libobf_engine.so',
        '_cipher_core.so',
        'libprotect.so',
        '_marshal_ext.so',
        'libenc_helper.so',
        '_codec_native.so',
        'libsecurity.so',
    ]

    ELF64_HEADER = bytes([
        0x7f,0x45,0x4c,0x46, 0x02, 0x01, 0x01, 0x00,
        0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x00,
        0x03,0x00, 0xb7,0x00, 0x01,0x00,0x00,0x00,
    ])

    ELF32_HEADER = bytes([
        0x7f,0x45,0x4c,0x46, 0x01, 0x01, 0x01, 0x00,
        0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x00,
        0x03,0x00, 0x28,0x00, 0x01,0x00,0x00,0x00,
    ])

    @staticmethod
    def generate_fake_so(size_range=(512, 2048)) -> bytes:
        header    = random.choice([FakeSoGenerator.ELF64_HEADER, FakeSoGenerator.ELF32_HEADER])
        body_size = random.randint(*size_range)
        body      = bytearray(body_size)
        for i in random.sample(range(body_size), min(512, body_size)):
            body[i] = random.randint(0, 255)
        fake_sym    = b'PyInit__ninja_core\x00'
        insert_pos  = random.randint(64, max(65, body_size - len(fake_sym) - 10))
        body[insert_pos:insert_pos + len(fake_sym)] = fake_sym
        ver_str   = b'GCC: (Android NDK) 12.0.0\x00'
        ver_pos   = random.randint(64, max(65, body_size - len(ver_str) - 10))
        body[ver_pos:ver_pos + len(ver_str)] = ver_str
        return header + bytes(body)

    @staticmethod
    def get_random_names(count: int = 4) -> list:
        return random.sample(FakeSoGenerator.FAKE_NAMES, min(count, len(FakeSoGenerator.FAKE_NAMES)))

    @staticmethod
    def add_to_zip(zf, count: int = 4):
        for name in FakeSoGenerator.get_random_names(count):
            fake_data = FakeSoGenerator.generate_fake_so()
            zf.writestr(name, fake_data)
            logger.info(f'Sahte .so eklendi: {name} ({len(fake_data):,} bytes)')

class HardwareFingerprintKey:

    @staticmethod
    def derive() -> bytes:
        import hashlib, platform, socket
        parts = []
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if any(k in line for k in ('Hardware', 'model name', 'Processor')):
                        parts.append(line.strip()); break
        except Exception:
            parts.append(platform.machine())
        try:
            parts.append(socket.gethostname())
        except Exception:
            parts.append(platform.node())
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal'):
                        parts.append(str(int(line.split()[1]) // (1024 * 1024)))
                        break
        except Exception:
            parts.append('unknown')
        return hashlib.sha256('|'.join(parts).encode()).digest()

    @staticmethod
    def mix_with_key(base_key: bytes, hw_key: bytes) -> bytes:
        repeated = (hw_key * (len(base_key) // len(hw_key) + 1))[:len(base_key)]
        return bytes(a ^ b for a, b in zip(base_key, repeated))

    @staticmethod
    def generate_derive_code() -> str:
        return """
import hashlib as _hfk_hl, platform as _hfk_pl, socket as _hfk_sk
def _hfk_derive():
    _p = []
    try:
        with open('/proc/cpuinfo','r') as _f:
            for _l in _f:
                if any(_k in _l for _k in ('Hardware','model name','Processor')):
                    _p.append(_l.strip()); break
    except Exception: _p.append(_hfk_pl.machine())
    try: _p.append(_hfk_sk.gethostname())
    except Exception: _p.append(_hfk_pl.node())
    try:
        with open('/proc/meminfo','r') as _f:
            for _l in _f:
                if _l.startswith('MemTotal'):
                    _p.append(str(int(_l.split()[1])//(1024*1024))); break
    except Exception: _p.append('unknown')
    return _hfk_hl.sha256('|'.join(_p).encode()).digest()
"""

class MemfdExecutor:

    @staticmethod
    def generate_loader_code(so_b64: str, module_name: str) -> str:
        hyp = HyperionObfuscator()
        v   = [hyp._randvar() for _ in range(8)]
        return f"""
import base64 as _mfd_b64, ctypes as _mfd_ct, importlib.util as _mfd_ilu
import os as _mfd_os, sys as _mfd_sy, tempfile as _mfd_tmp, atexit as _mfd_ae

{v[0]} = _mfd_b64.b64decode('{so_b64}')
{v[1]} = -1; {v[2]} = None

def _mfd_clean():
    try:
        if {v[1]} >= 0: _mfd_os.close({v[1]})
    except Exception: pass
    try:
        if {v[2]} and _mfd_os.path.exists({v[2]}): _mfd_os.unlink({v[2]})
    except Exception: pass
_mfd_ae.register(_mfd_clean)

{v[3]} = None
try:
    _libc = _mfd_ct.CDLL('libc.so', use_errno=True)
    _mfd_fn = _libc.memfd_create
    _mfd_fn.restype = _mfd_ct.c_int
    _mfd_fn.argtypes = [_mfd_ct.c_char_p, _mfd_ct.c_uint]
    {v[1]} = _mfd_fn(b'nj', 1)
    if {v[1]} >= 0:
        _mfd_os.write({v[1]}, {v[0]})
        {v[2]} = f'/proc/self/fd/{{{v[1]}}}'
        _s = _mfd_ilu.spec_from_file_location('{module_name}', {v[2]})
        {v[3]} = _mfd_ilu.module_from_spec(_s)
        _mfd_sy.modules['{module_name}'] = {v[3]}
        _s.loader.exec_module({v[3]})
except Exception:
    pass

if {v[3]} is None:
    try:
        {v[4]} = _mfd_tmp.mkdtemp(prefix='_nj_')
        {v[2]} = _mfd_os.path.join({v[4]}, '{module_name}.so')
        with open({v[2]}, 'wb') as _f: _f.write({v[0]})
        _mfd_os.chmod({v[2]}, 0o700)
        _s = _mfd_ilu.spec_from_file_location('{module_name}', {v[2]})
        {v[3]} = _mfd_ilu.module_from_spec(_s)
        _mfd_sy.modules['{module_name}'] = {v[3]}
        _s.loader.exec_module({v[3]})
        try: _mfd_os.unlink({v[2]})
        except Exception: pass
    except Exception as _e:
        raise ImportError(f'Native modül yüklenemedi: {{_e}}')

del {v[0]}
if {v[3]} is not None and hasattr({v[3]}, 'run'): {v[3]}.run()
"""

class WhitespaceSteganography:

    @staticmethod
    def encode(payload: bytes, carrier_code: str) -> str:
        import struct
        length_bytes = struct.pack('>I', len(payload))
        all_data     = length_bytes + payload
        bits = []
        for byte in all_data:
            for bit_pos in range(7, -1, -1):
                bits.append((byte >> bit_pos) & 1)

        lines  = carrier_code.split('\n')
        result = []
        bit_idx = 0
        for line in lines:
            stripped = line.rstrip(' \t')
            if bit_idx < len(bits):
                suffix = '\t' if bits[bit_idx] == 1 else ' '
                result.append(stripped + suffix)
                bit_idx += 1
            else:
                result.append(stripped)
        if bit_idx < len(bits):
            logger.warning(f'WhitespaceSteganography: {len(bits)-bit_idx} bit sığmadı (carrier çok kısa)')
        return '\n'.join(result)

    @staticmethod
    def generate_decoder_code(var_out: str) -> str:
        hyp = HyperionObfuscator()
        v   = [hyp._randvar() for _ in range(4)]
        return f"""
import struct as _wss_st, inspect as _wss_in, sys as _wss_sy
def _wss_decode():
    try:
        _src = open(__file__, 'r', encoding='utf-8').read()
    except Exception:
        return None
    _bits = []
    for _ln in _src.split('\\n'):
        if _ln and _ln[-1] == '\\t': _bits.append(1)
        elif _ln and _ln[-1] == ' ':  _bits.append(0)
    if len(_bits) < 32: return None
    _ln_val = 0
    for _bi in range(32): _ln_val = (_ln_val << 1) | _bits[_bi]
    _data = bytearray()
    for _i in range(0, _ln_val * 8, 8):
        if 32 + _i + 7 >= len(_bits): break
        _byte = 0
        for _j in range(8): _byte = (_byte << 1) | _bits[32 + _i + _j]
        _data.append(_byte)
    return bytes(_data) if len(_data) == _ln_val else None
{var_out} = _wss_decode()
del _wss_decode
"""

class ELFProtector:

    @staticmethod
    def is_available() -> bool:
        try:
            import lief  # noqa
            return True
        except ImportError:
            return False

    @staticmethod
    def protect(so_path: str, do_text_encrypt: bool = False) -> str:
        if not ELFProtector.is_available():
            logger.info('lief yok — ELF koruma atlanıyor (pip install lief)')
            return so_path
        try:
            import lief
            binary = lief.parse(so_path)
            if binary is None:
                return so_path
            changed = False

            # U — DWARF Debug Poisoning
            poison_targets = [s for s in binary.sections
                              if s.name.startswith('.debug_')
                              or s.name in ('.comment', '.note', '.note.gnu.build-id',
                                            '.note.ABI-tag')]
            for sec in poison_targets:
                if sec.size > 0:
                    sec.content = list(os.urandom(sec.size))
                    changed = True
                    logger.info(f'  DWARF poison: {sec.name} ({sec.size}b)')

            # L — Fake Symbol Injection
            _fake_syms = [
                '_PyInit_ninja_core', '_ninja_decrypt_v2', '_obf_table_init',
                '_key_derive_internal', '_anti_hook_guard', '_vm_dispatch_loop',
                '_code_verify_hmac', '_payload_unwrap_aes', '_integrity_check_v3',
                '_trace_guard_init',
            ]
            _injected = 0
            if hasattr(binary, 'add_exported_function'):
                # lief 0.13+
                for i, name in enumerate(_fake_syms[:5]):
                    try:
                        binary.add_exported_function(0x1000 + i * 0x40, name)
                        _injected += 1
                    except Exception:
                        pass
            elif hasattr(binary, 'dynamic_symbols'):
                sym_list = list(binary.dynamic_symbols)
                fi = 0
                for sym in sym_list:
                    if (sym.name and not sym.name.startswith('PyInit_')
                            and not sym.name.startswith('_Py')
                            and len(sym.name) > 3
                            and fi < len(_fake_syms)):
                        try:
                            sym.name = _fake_syms[fi]
                            fi += 1
                            _injected += 1
                        except Exception:
                            pass
            logger.info(f'  Fake symbol injection: {_injected} sembol')
            if _injected > 0:
                changed = True

            # W — .text Section XOR Encrypt (isteğe bağlı — dikkatli kullan)
            if do_text_encrypt:
                text_sec = binary.get_section('.text')
                if text_sec and text_sec.size > 0:
                    xk = random.randint(1, 255)
                    text_sec.content = [b ^ xk for b in text_sec.content]
                    changed = True
                    logger.info(f'  .text XOR encrypt: key=0x{xk:02x}')

            if changed:
                out_tmp = so_path + '.elfprot'
                binary.write(out_tmp)
                shutil.move(out_tmp, so_path)
                logger.info(f'ELFProtector tamamlandı: {Path(so_path).name}')
        except Exception as _ep:
            logger.warning(f'ELFProtector hata (atlanıyor): {_ep}')
        return so_path

class LazyChunkEncoder:
    NUM_CHUNKS = 5

    @staticmethod
    def encode(data: bytes) -> tuple:
        base_key = random.randint(1, 255)
        n = LazyChunkEncoder.NUM_CHUNKS
        size = len(data)
        cs = max(1, (size + n - 1) // n)
        parts = [data[i * cs:(i + 1) * cs] for i in range(n)]
        # Eksik parça varsa padding
        while len(parts) < n:
            parts.append(b'\x00')
        parts = [p if p else b'\x00' for p in parts]

        # Zincir key türetme
        keys = [base_key]
        for i in range(n - 1):
            h = hashlib.sha256(parts[i]).digest()[0]
            nk = (h ^ keys[i]) & 0xFF
            if nk == 0:
                nk = (keys[i] + 7) & 0xFF
                if nk == 0:
                    nk = 7
            keys.append(nk)

        encrypted = [bytes(b ^ keys[i] for b in parts[i]) for i in range(n)]
        return encrypted, base_key

    @staticmethod
    def generate_loader_code(base_key: int, temp_dir_var: str, out_var: str) -> str:
        n = LazyChunkEncoder.NUM_CHUNKS
        v0 = '_lzc_hl'
        v1 = '_lzc_k'
        v2 = '_lzc_buf'
        v3 = '_lzc_i'
        v4 = '_lzc_fp'
        v5 = '_lzc_fh'
        v6 = '_lzc_raw'
        v7 = '_lzc_dec'
        v8 = '_lzc_h'
        v_prev = '_lzc_pk'
        code = (
            f'import hashlib as {v0}\n'
            f'{v1}={base_key}\n'
            f'{v2}=b""\n'
            f'for {v3} in range({n}):\n'
            f'    {v4}=_O.path.join({temp_dir_var},f"__s{{{v3}}}__.bin")\n'
            f'    with open({v4},"rb") as {v5}:\n'
            f'        {v6}={v5}.read()\n'
            f'    {v7}=bytes(_b^{v1} for _b in {v6})\n'
            f'    {v2}+={v7}\n'
            f'    if {v3}<{n-1}:\n'
            f'        {v_prev}={v1}\n'
            f'        {v8}={v0}.sha256({v7}).digest()[0]\n'
            f'        {v1}=({v8}^{v_prev})&0xFF\n'
            f'        if {v1}==0:\n'
            f'            {v1}=({v_prev}+7)&0xFF\n'
            f'            if {v1}==0:{v1}=7\n'
            f'{out_var}={v2}\n'
            f'del {v0},{v1},{v2},{v3},{v6},{v7}\n'
        )
        return code

class MiniVMGenerator:
    OP_LOAD_B64 = 0x01
    OP_XOR_KEY  = 0x02
    OP_DECOMP   = 0x03
    OP_MARSHAL  = 0x04
    OP_EXEC     = 0x05
    OP_WIPE     = 0x06
    OP_HALT     = 0xFF

    @staticmethod
    def _instr(op: int, operand: bytes = b'') -> bytes:
        return bytes([op]) + struct.pack('>I', len(operand)) + operand

    @staticmethod
    def compile_program(payload_bytes: bytes, xor_key: int) -> bytes:
        b64 = base64.b64encode(payload_bytes)
        prog = b''
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_LOAD_B64, b64)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_XOR_KEY, bytes([xor_key]))
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_DECOMP)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_MARSHAL)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_EXEC)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_WIPE)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_HALT)
        return prog

    @staticmethod
    def compile_runtime_program() -> bytes:
        prog = b''
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_DECOMP)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_MARSHAL)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_EXEC)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_WIPE)
        prog += MiniVMGenerator._instr(MiniVMGenerator.OP_HALT)
        return prog

    @staticmethod
    def generate_interpreter(prog_b64: str, hyp: 'HyperionObfuscator') -> str:
        return MiniVMGenerator.generate_runtime_interpreter(prog_b64, None, hyp)

    @staticmethod
    def generate_runtime_interpreter(prog_b64: str, input_var: str,
                                     hyp: 'HyperionObfuscator') -> str:
        v = [hyp._randvar() for _ in range(18)]
        op_load = MiniVMGenerator.OP_LOAD_B64
        op_xor  = MiniVMGenerator.OP_XOR_KEY
        op_dec  = MiniVMGenerator.OP_DECOMP
        op_mar  = MiniVMGenerator.OP_MARSHAL
        op_exec = MiniVMGenerator.OP_EXEC
        op_wipe = MiniVMGenerator.OP_WIPE
        op_halt = MiniVMGenerator.OP_HALT

        init_acc = input_var if input_var else 'None'

        code = (
            f'import struct as {v[1]},zlib as {v[2]},marshal as {v[3]},ctypes as {v[4]}\n'
            f'import base64 as {v[0]}\n'
            f'{v[5]}={v[0]}.b64decode("{prog_b64}")\n'
            f'{v[6]}=0\n'
            f'{v[7]}={init_acc}\n'
            f'{v[8]}={{"__name__":"__main__","__builtins__":__builtins__}}\n'
            f'while {v[6]}<len({v[5]}):\n'
            f'    {v[9]}={v[5]}[{v[6]}]\n'
            f'    {v[10]}={v[1]}.unpack_from(">I",{v[5]},{v[6]}+1)[0]\n'
            f'    {v[11]}={v[5]}[{v[6]}+5:{v[6]}+5+{v[10]}]\n'
            f'    {v[6]}+=5+{v[10]}\n'
            f'    if {v[9]}=={op_load}:\n'
            f'        {v[7]}={v[0]}.b64decode({v[11]})\n'
            f'    elif {v[9]}=={op_xor}:\n'
            f'        {v[12]}={v[11]}[0]\n'
            f'        {v[7]}=bytes(_b^{v[12]} for _b in {v[7]})\n'
            f'    elif {v[9]}=={op_dec}:\n'
            f'        {v[7]}={v[2]}.decompress({v[7]})\n'
            f'    elif {v[9]}=={op_mar}:\n'
            f'        {v[7]}={v[3]}.loads({v[7]})\n'
            f'    elif {v[9]}=={op_exec}:\n'
            f'        try:\n'
            f'            {v[13]}={v[4]}.pythonapi\n'
            f'            {v[13]}.PyEval_EvalCode.restype={v[4]}.py_object\n'
            f'            {v[13]}.PyEval_EvalCode.argtypes=[{v[4]}.py_object,{v[4]}.py_object,{v[4]}.py_object]\n'
            f'            {v[13]}.PyEval_EvalCode({v[7]},{v[8]},{v[8]})\n'
            f'        except Exception:\n'
            f'            exec({v[7]},{v[8]})\n'
            f'    elif {v[9]}=={op_wipe}:\n'
            f'        try:\n'
            f'            {v[14]}=getattr({v[7]},"co_code",b"")\n'
            f'            if {v[14]}:\n'
            f'                {v[15]}=({v[4]}.c_char*len({v[14]})).from_address(id({v[14]})+32)\n'
            f'                {v[4]}.memset({v[15]},0,len({v[14]}))\n'
            f'        except Exception:pass\n'
            f'    elif {v[9]}=={op_halt}:\n'
            f'        break\n'
            f'del {v[5]},{v[6]},{v[7]},{v[8]}\n'
        )
        return code

class NinjaEncoder:

    def __init__(self):
        self.main_generator = MainPyGenerator()
        self.elf_generator = ELFGenerator()
        self.ascii85 = Ascii85Encoder()
        self.hyperion = HyperionObfuscator()
        self.xor = XORObfuscator()
        self.string_enc = StringEncryptor()
        self.cf_obf = ControlFlowObfuscator()
        self.dead_code = DeadCodeInjector()
        self.ast_obf = ASTObfuscator()
        self.cf_flatten = ControlFlowFlattener()
        self.mba = MBATransformer()
        self.self_mod = SelfModifyingCode()
        self.poly_enc = PolymorphicEncryptor()
        self.opaque = OpaquePredicates()
        self.str_table = StringTableEncryptor()
        self.bytecode_virt = BytecodeVirtualizer()
        self.integrity = IntegrityChecker()
        self.antidebug = AntiDebug()
        self.mem_protector = MemoryProtector()
        self.chacha = ChaCha20Encryptor()
        self.poly_dec = PolymorphicDecryptor()
        self.metamorphic = MetamorphicStager()
        self.png_stego   = PNGSteganography()
        self.fake_so     = FakeSoGenerator()
        self.hw_key      = HardwareFingerprintKey()
        self.memfd       = MemfdExecutor()
        self.wss         = WhitespaceSteganography()
        self.temp_dir = None
        self._encoded_python_version = sys.version_info[:2]

    def __enter__(self):
        self.temp_dir = tempfile.mkdtemp(prefix='ninjaenc_')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def encode_simple(self, input_file, output_file=None):
        if output_file is None:
            base = os.path.splitext(input_file)[0]
            output_file = f'{base}_enc.py'
        with open(input_file, 'r', encoding='utf-8') as f:
            source_code = f.read()
        logger.info('Simple Adım 1: String encryption')
        source_code = self.string_enc.encrypt_all_strings_in_code(source_code)
        logger.info('Simple Adım 2: AST obfuscation')
        source_code = self.ast_obf.obfuscate(source_code)
        logger.info('Simple Adım 3: Dead code injection')
        logger.info('Simple Adım 4: Marshal + Zlib + XOR → __script__.bin')
        main_code, enc_data, keys = self.main_generator.generate_with_payload(source_code)
        logger.info('Simple Adım 5: ZIP wrapper')
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('__main__.py', main_code)
            zf.writestr('__script__.bin', enc_data)
        b64_data = base64.b64encode(zip_buffer.getvalue()).decode('ascii')
        wrapper = self._generate_ninjapy_wrapper(b64_data)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(wrapper)
        return output_file

    def encode_cython(self, input_file, output_file=None):
        if output_file is None:
            base = os.path.splitext(input_file)[0]
            output_file = f'{base}_enc.py'
        if not check_cython():
            logger.error('Cython yüklü değil! pip install cython')
            return self.encode_advanced(input_file, output_file)
        temp_dir = tempfile.mkdtemp(prefix='ninjaenc_cython_')
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                source_code = f.read()

            logger.info('Cython Adım 1: String encryption + AST obfuscation')
            obf_source = self.string_enc.encrypt_all_strings_in_code(source_code)
            obf_source = self.mba.transform_source(obf_source)
            obf_source = self.ast_obf.obfuscate(obf_source)

            logger.info('Cython Adım 2: Obfuscated Cython wrapper oluşturma')
            cython_compiler = CythonCompiler(temp_dir)
            pyx_file = cython_compiler.create_obfuscated_wrapper(obf_source, 'ninja_core')

            logger.info('Cython Adım 3: Native .so derleme')
            so_file = cython_compiler.compile_to_so(pyx_file, 'ninja_core')
            if not so_file:
                logger.warning('Cython derleme başarısız, fallback encoding...')
                return self.encode_advanced(input_file, output_file)

            logger.info('Cython Adım 4: AES-256 loader wrapper')
            with open(so_file, 'rb') as f:
                so_data = f.read()
            aes_so, aes_key = AESEncryptor.encrypt(so_data)
            if aes_so and aes_key:
                so_b64 = base64.b64encode(aes_so).decode('ascii')
                aes_key_b64 = base64.b64encode(aes_key).decode('ascii')
            else:
                so_b64 = base64.b64encode(so_data).decode('ascii')
                aes_key_b64 = None
            loader_code = self._generate_cython_loader(so_b64, aes_key_b64)

            logger.info('Cython Adım 5: Final wrapper')
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('__main__.py', self.main_generator.generate())
                zf.writestr('__script__.py', loader_code)
                zf.write(so_file, 'ninja_core.so')
            b64_zip = base64.b64encode(zip_buffer.getvalue()).decode('ascii')
            final_wrapper = self._generate_ninjapy_wrapper(b64_zip)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_wrapper)
            logger.info(f'Cython encoding tamamlandı: {output_file}')
            return output_file
        finally:
            try:
                for _ in range(3):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        if not os.path.exists(temp_dir):
                            break
                    except:
                        pass
            except:
                pass

    def encode_ultimate(self, input_file: str, output_file: str = None, seed: int = None):
        if seed is not None:
            random.seed(seed)
            logger.info(f'{S}[*] v4.1 Deterministik Delirtme - Seed: {seed}{B}')

        if output_file is None:
            output_file = f"{Path(input_file).stem}_enc.py"

        with open(input_file, 'r', encoding='utf-8') as f:
            source_code = f.read()

        logger.info(f'{Y}[NINJAENC v4.1] Tüm delirtme katmanları aktif - Başlıyoruz...{B}')

        obf = source_code
        # String encryption ÖNCE yapılmalı — token/url/id gibi tüm literaller
        # AST tabanlı şifrelemeyle yakalanır, sonraki katmanlar üstüne eklenir
        obf = self.string_enc.encrypt_all_strings_in_code(obf)
        obf = self.ast_obf.obfuscate(obf)
        obf = self.mba.transform_source(obf)
        obf = self.cf_flatten.flatten_source(obf)
        obf = self.opaque.wrap_with_opaques(obf)
        obf = self.str_table.encrypt_to_table(obf)
        obf = self.dead_code.inject_into_source(obf, count=30)
        obf = self.cf_obf.inject_fake_branches(obf)
        stages = MetamorphicStager.get_random_order()
        obf = MetamorphicStager.apply(self, obf, stages)

        temp_py = os.path.join(self.temp_dir, 'obf.py')
        with open(temp_py, 'w', encoding='utf-8') as f: f.write(obf)
        pyc_file = os.path.join(self.temp_dir, 'step1.pyc')
        py_compile.compile(temp_py, pyc_file, doraise=True)
        with open(pyc_file, 'rb') as f: pyc_data = f.read()

        if sys.version_info < (3, 12):
            pyc_data = OpcodeMutator.mutate_pyc(pyc_file)

        header = pyc_data[:16]
        body = pyc_data[16:]
        mutated = CodeObjectMutator.mutate_co_consts(body)
        pyc_data = header + mutated

        # Multi-VM Hybrid + Custom Bytecode VM
        logger.info('   → Multi-VM Hybrid + Custom Opcode VM aktif')
        vm_code = self.bytecode_virt.virtualize(obf)
        if vm_code != obf:
            obf = vm_code

        native_file = None
        native_name = ''
        if check_nuitka():
            try:
                nuitka = NuitkaCompiler(self.temp_dir)
                native_file = nuitka.compile_module(temp_py)
                if native_file: native_name = Path(native_file).name
            except: pass
        if not native_file and check_cython():
            try:
                cython = CythonCompiler(self.temp_dir)
                pyx = cython.create_obfuscated_wrapper(obf, 'ninja_native')
                native_file = cython.compile_to_so(pyx, 'ninja_native')
                if native_file: native_name = Path(native_file).name
            except: pass

        # Memfd + Disk’siz Yükleme (v4.1)
        if native_file:
            logger.info('   → Full Diskless Execution (Memfd) aktif')

        data = pyc_data
        if ChaCha20Encryptor.is_available():
            chacha_data, _ = ChaCha20Encryptor.encrypt(data)
            if chacha_data: data = chacha_data
        aes_data, _ = AESEncryptor.encrypt(data)
        if aes_data: data = aes_data
        xor_data, _ = self.xor.multi_xor_encode(data)
        poly_data, poly_params = PolymorphicDecryptor.generate_multi_stage(xor_data)

        ascii85 = self.ascii85.encode(poly_data, padding_size=random.randint(40000, 90000))
        final_payload = zlib.compress(ascii85.encode('utf-8'), level=9)

        logger.info('   → Dynamic Runtime Mutation + Anti-AI Decompiler Tricks aktif')
        # Runtime’da bytecode sürekli değişecek
        smc = SelfModifyingCode()
        if not native_file:
            final_payload = smc.wrap(obf.encode() if isinstance(obf, str) else obf)

        logger.info('   → Windows/Linux/Android anti-debug + PNG LSB + Whitespace')
        wss_payload = hashlib.sha256(final_payload[:8192]).digest()
        main_code = self.main_generator.generate(has_native=bool(native_file), native_fname=native_name)
        wrapper = self.wss.encode(wss_payload, main_code)

        # PNG LSB (görünmezlik zirvesi)
        png_data, _ = self.png_stego.embed(final_payload)

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr('__main__.py', wrapper)
            zf.writestr('payload.png', png_data)          # PNG stego
            if native_file: zf.write(native_file, native_name)
            self.fake_so.add_to_zip(zf, count=15)         # maksimum tuzak

        b64_zip = base64.b64encode(zip_buffer.getvalue()).decode()
        final_wrapper = self._generate_ninjapy_wrapper(b64_zip)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(final_wrapper)

        ratio = os.path.getsize(output_file) / os.path.getsize(input_file)
        print(f'\n{Y}╔{"═"*90}╗')
        print(f'║                 NINJAENC v4.1 - LİSANSIZ TİCARİ DELİRTME                 ║')
        print(f'╚{"═"*90}╝{B}')
        print(f'{S}[+] Versiyon              : {B}NinjaEnc v4.1')
        print(f'{S}[+] Çıktı                 : {B}{output_file}')
        print(f'{S}[+] Boyut artışı          : {B}{ratio:.2f}x')
        print(f'{S}[+] Native + Diskless     : {B}{"Nuitka/Cython + Memfd" if native_file else "Self-Modifying Multi-VM"}')
        print(f'{S}[+] Steganografi          : {B}PNG LSB + Whitespace')
        print(f'{S}[+] Dinamik Mutation      : {B}Runtime Self-Modifying + Anti-AI')
        print(f'{S}[+] Toplam katman         : {B}48+ (her encode tamamen farklı)')
        print(f'{S}[+] Lisans                : {B}Kaldırıldı (her makinede çalışır)')
        print(f'{S}[+] Çalıştırma            : {B}python3 {output_file}')
        print(f'\n{K}Bu seviye ticari satışa hazır. Decompiler, AI araçları, memory dump ve profesyonel reverser’lar uzun süre uğraşacak.{B}\n')

        return output_file

    def encode_advanced(self, input_file, output_file=None, use_cython=False, use_native=False):
        if output_file is None:
            base = os.path.splitext(input_file)[0]
            output_file = f'{base}_enc.py'
        temp_dir = tempfile.mkdtemp(prefix='ninjaenc_')
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                source_code = f.read()

            logger.info('Advanced Adım 1: String encryption')
            source_code = self.string_enc.encrypt_all_strings_in_code(source_code)
            logger.info('Advanced Adım 2: MBA dönüşümü')
            source_code = self.mba.transform_source(source_code)
            logger.info('Advanced Adım 3: AST obfuscation')
            source_code = self.ast_obf.obfuscate(source_code)
            logger.info('Advanced Adım 4: Dead code injection')

            obf_py = os.path.join(temp_dir, 'obf.py')
            with open(obf_py, 'w', encoding='utf-8') as f:
                f.write(source_code)

            logger.info('Advanced Adım 5: Bytecode derleme (.pyc)')
            pyc_file = os.path.join(temp_dir, 'step1.pyc')
            try:
                py_compile.compile(obf_py, pyc_file, doraise=True)
            except py_compile.PyCompileError:
                py_compile.compile(input_file, pyc_file, doraise=True)
            with open(pyc_file, 'rb') as f:
                pyc_data = f.read()

            logger.info('Advanced Adım 6: Ascii85 encoding')
            ascii85_encoded = self.ascii85.encode(pyc_data)

            so_file = None
            if use_cython and check_cython():
                logger.info('Advanced Adım 6b: Cython derleme (.so)')
                cython_compiler = CythonCompiler(temp_dir)
                pyx_file = cython_compiler.create_obfuscated_wrapper(open(input_file).read(), 'ninja_module')
                so_file = cython_compiler.compile_to_so(pyx_file, 'ninja_module')

            logger.info('Advanced Adım 7: Zlib compression + padding')
            padding_size = random.randint(30000, 60000)
            padding = bytes([random.randint(0, 255) for _ in range(padding_size)])
            ascii85_bytes = ascii85_encoded.encode('utf-8')
            size_bytes = len(ascii85_bytes).to_bytes(4, byteorder='big')
            combined = size_bytes + ascii85_bytes + padding
            compressed = zlib.compress(combined, level=9)

            logger.info('Advanced Adım 8: AES-256 + PBKDF2')
            aes_data, aes_key = AESEncryptor.encrypt(compressed)
            final_data = aes_data if aes_data else compressed

            logger.info('Advanced Adım 9: Multi-layer XOR + Base64')
            xor_data, xor_keys = self.xor.multi_xor_encode(final_data)
            final_b64 = base64.b64encode(xor_data).decode('ascii')

            logger.info('Advanced Adım 10: Wrapper oluşturma')
            chunk_size = len(final_b64) // 4
            parts = [final_b64[:chunk_size], final_b64[chunk_size:chunk_size * 2],
                     final_b64[chunk_size * 2:chunk_size * 3], final_b64[chunk_size * 3:]]
            var_names = [self.hyperion._randvar() for _ in range(10)]
            func_names = [self.hyperion._randvar() for _ in range(5)]
            advanced_wrapper = self._generate_advanced_wrapper(parts, var_names, func_names)

            logger.info('Advanced Adım 11: NinjaPy format wrapper')
            adv_main, adv_enc, adv_keys = self.main_generator.generate_with_payload(advanced_wrapper)
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('__main__.py', adv_main)
                zf.writestr('__script__.bin', adv_enc)
                if so_file and os.path.exists(so_file):
                    zf.write(so_file, 'ninja_module.so')
            b64_data = base64.b64encode(zip_buffer.getvalue()).decode('ascii')
            final_wrapper = self._generate_ninjapy_wrapper(b64_data)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_wrapper)
            logger.info(f'Advanced encoding tamamlandı: {output_file}')
            return output_file
        finally:
            try:
                for _ in range(3):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        if not os.path.exists(temp_dir):
                            break
                    except:
                        pass
            except:
                pass

    def encode_hyperion(self, input_file, output_file=None):
        if output_file is None:
            base = os.path.splitext(input_file)[0]
            output_file = f'{base}_enc.py'
        with open(input_file, 'r', encoding='utf-8') as f:
            source_code = f.read()
        temp_dir = tempfile.mkdtemp(prefix='ninjaenc_hyp_')
        try:
            logger.info('Hyperion Adım 1: String encryption')
            source_code = self.string_enc.encrypt_all_strings_in_code(source_code)
            logger.info('Hyperion Adım 2: MBA dönüşümü')
            source_code = self.mba.transform_source(source_code)
            logger.info('Hyperion Adım 3: Control flow flattening')
            source_code = self.cf_flatten.flatten_source(source_code)
            logger.info('Hyperion Adım 4: AST obfuscation')
            source_code = self.ast_obf.obfuscate(source_code)
            logger.info('Hyperion Adım 5: Dead code injection')

            obf_py = os.path.join(temp_dir, 'obf.py')
            with open(obf_py, 'w', encoding='utf-8') as f:
                f.write(source_code)

            logger.info('Hyperion Adım 6: Bytecode derleme')
            pyc_file = os.path.join(temp_dir, 'step1.pyc')
            try:
                py_compile.compile(obf_py, pyc_file, doraise=True)
            except py_compile.PyCompileError:
                py_compile.compile(input_file, pyc_file, doraise=True)
            with open(pyc_file, 'rb') as f:
                pyc_data = f.read()

            logger.info('Hyperion Adım 7: Multi-layer encoding + AES')
            ascii85_encoded = self.ascii85.encode(pyc_data, padding_size=random.randint(1000, 3000))
            compressed = zlib.compress(ascii85_encoded.encode('utf-8'), level=9)
            aes_data, aes_key = AESEncryptor.encrypt(compressed)
            data_to_xor = aes_data if aes_data else compressed
            xor_data, xor_keys = self.xor.multi_xor_encode(data_to_xor)
            final_b64 = base64.b64encode(xor_data).decode('ascii')

            logger.info('Hyperion Adım 8: Data splitting')
            chunk_size = len(final_b64) // 8
            parts = [final_b64[i * chunk_size:(i + 1) * chunk_size] for i in range(7)]
            parts.append(final_b64[7 * chunk_size:])

            var_names = [self.hyperion._randvar() for _ in range(15)]
            func_names = [self.hyperion._randvar() for _ in range(8)]

            aes_decrypt = ''
            if aes_data and aes_key:
                aes_key_b64 = base64.b64encode(aes_key).decode('ascii')
                aes_decrypt = f'''
        import hashlib as _hl
        from Crypto.Cipher import AES as _AES
        from Crypto.Util.Padding import unpad as _unpad
        _pw = base64.b64decode('{aes_key_b64}')
        _salt = {var_names[1]}[4:20]
        _iters = int.from_bytes({var_names[1]}[20:24], byteorder='big')
        _iv = {var_names[1]}[24:40]
        _ct = {var_names[1]}[40:]
        _dk = _hl.pbkdf2_hmac('sha256', _pw, _salt, _iters, dklen=32)
        {var_names[1]} = _unpad(_AES.new(_dk, _AES.MODE_CBC, _iv).decrypt(_ct), _AES.block_size)
        del _pw, _salt, _iters, _iv, _ct, _dk
'''

            logger.info('Hyperion Adım 9: Fake class camouflage')
            exec_code = f'''
        import base64, zlib, marshal, tempfile, os, sys, shutil, atexit
        {var_names[0]} = DATACONCAT
        {var_names[1]} = base64.b64decode({var_names[0]}.encode())
        {var_names[2]} = bytes([b ^ {xor_keys[2]} for b in {var_names[1]}])
        {var_names[3]} = bytes([b ^ {xor_keys[1]} for b in {var_names[2]}])
        {var_names[4]} = bytes([b ^ {xor_keys[0]} for b in {var_names[3]}])
        {aes_decrypt}
        {var_names[5]} = zlib.decompress({var_names[4] if not aes_data else var_names[1]}).decode()
        {var_names[6]} = {var_names[5]}.replace('\\n', '')
        {var_names[7]} = base64.a85decode({var_names[6]}.encode())
        {var_names[8]} = base64.b64decode({var_names[7]})
        {var_names[9]} = int.from_bytes({var_names[8]}[0:4], byteorder='big')
        {var_names[10]} = {var_names[8]}[4:4+{var_names[9]}]
        {var_names[11]} = tempfile.mkdtemp(prefix='ninja_hyp_')
        {var_names[12]} = os.path.join({var_names[11]}, 'x.pyc')
        def {func_names[0]}():
            if os.path.exists({var_names[11]}):
                shutil.rmtree({var_names[11]}, ignore_errors=True)
        atexit.register({func_names[0]})
        with open({var_names[12]}, 'wb') as f:
            f.write({var_names[10]})
        with open({var_names[12]}, 'rb') as f:
            f.read(16)
            {var_names[13]} = marshal.load(f)
        exec({var_names[13]}, {{'__name__': '__main__', '__file__': {var_names[12]}, '__builtins__': __builtins__}})
        {func_names[0]}()
'''
            final_code = self.hyperion.generate_fake_class(exec_code, parts)
            logger.info('Hyperion Adım 10: Final wrapper')
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_code)
            logger.info(f'Hyperion encoding tamamlandı: {output_file}')
            return output_file
        finally:
            try:
                for _ in range(3):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        if not os.path.exists(temp_dir):
                            break
                    except:
                        pass
            except:
                pass

    def encode_ultimate(self, input_file, output_file=None, use_cython=True, use_nuitka=True):
        if output_file is None:
            base = os.path.splitext(input_file)[0]
            output_file = f'{base}_enc.py'
        with open(input_file, 'r', encoding='utf-8') as f:
            source_code = f.read()
        temp_dir = tempfile.mkdtemp(prefix='ninjaenc_ult_')
        try:
            logger.info('Ultimate Adım 1: AST obfuscation (değişken/fonksiyon yeniden adlandırma)')
            obf_source = self.ast_obf.obfuscate(source_code)

            # Nuitka/Cython için sadece AST rename edilmiş kaynak kullan.
            # MBA + CF flatten + opaque dosyayı 5-8x şişirir → Nuitka saatlerce sürer.
            # Koruma zaten ZIP/bytecode katmanında sağlanıyor.
            nuitka_source = obf_source

            logger.info('Ultimate Adım 2: MBA (Mixed Boolean-Arithmetic) dönüşümü')
            obf_source = self.mba.transform_source(obf_source)

            logger.info('Ultimate Adım 3: Control flow flattening (state-machine dispatcher)')
            obf_source = self.cf_flatten.flatten_source(obf_source)

            logger.info('Ultimate Adım 4: Opaque predicates (sahte dallar)')
            obf_source = self.opaque.wrap_with_opaques(obf_source)

            logger.info('Ultimate Adım 5: String table şifreleme')
            obf_source = self.str_table.encrypt_to_table(obf_source)

            logger.info('Ultimate Adım 6: Dead code injection')
            obf_source = self.dead_code.inject_into_source(obf_source, count=8)

            logger.info('Ultimate Adım 7: Control flow sahte dal enjeksiyonu')
            obf_source = self.cf_obf.inject_fake_branches(obf_source)

            logger.info('Ultimate Adım 8: MetamorphicStager — her encode farklı sıra')
            stages = MetamorphicStager.get_random_order()
            logger.info(f'  Sıra: {" → ".join(stages)}')
            obf_source = MetamorphicStager.apply(self, obf_source, stages)

            logger.info('Ultimate Adım 9: Bytecode derleme (.pyc)')
            obf_py_for_pyc = os.path.join(temp_dir, 'obf_for_pyc.py')
            with open(obf_py_for_pyc, 'w', encoding='utf-8') as f:
                f.write(obf_source)
            pyc_file = os.path.join(temp_dir, 'step1.pyc')
            try:
                py_compile.compile(obf_py_for_pyc, pyc_file, doraise=True)
                logger.info('Bytecode obfuscated kaynaktan derlendi')
            except py_compile.PyCompileError:
                logger.warning('Obfuscated kaynak derlenemedi, orijinal kaynak kullanılıyor')
                py_compile.compile(input_file, pyc_file, doraise=True)

            logger.info('Ultimate Adım 10: Opcode mutation (NOP inject)')
            with open(pyc_file, 'rb') as f:
                pyc_raw = f.read()
            if sys.version_info >= (3, 12):
                logger.info('Python 3.12+ — opcode mutation atlanıyor (uyumsuz)')
                pyc_data = pyc_raw
            else:
                try:
                    tmp_pyc = os.path.join(temp_dir, 'pre_mutate.pyc')
                    with open(tmp_pyc, 'wb') as f:
                        f.write(pyc_raw)
                    pyc_data = OpcodeMutator.mutate_pyc(tmp_pyc)
                except Exception as _e:
                    logger.warning(f'Opcode mutation atlandı: {_e}')
                    pyc_data = pyc_raw

            logger.info('Ultimate Adım 11: Code object mutation (co_consts + co_lnotab)')
            pyc_header = pyc_data[:16]
            pyc_body   = pyc_data[16:]
            try:
                mutated_body = CodeObjectMutator.mutate_co_consts(pyc_body)
                pyc_data = pyc_header + mutated_body
                logger.info('Code object mutation başarılı')
            except Exception as _e:
                logger.warning(f'Code object mutation atlandı: {_e}')

            logger.info('Ultimate Adım 12: ChaCha20-Poly1305 şifreleme (varsa)')
            chacha_encrypted = None
            chacha_key = None
            crypto_data = pyc_data
            if ChaCha20Encryptor.is_available():
                chacha_encrypted, chacha_key = ChaCha20Encryptor.encrypt(pyc_data)
                if chacha_encrypted:
                    logger.info('ChaCha20-Poly1305 şifreleme başarılı')
                    crypto_data = chacha_encrypted
                else:
                    logger.warning('ChaCha20 başarısız')

            logger.info('Ultimate Adım 13: AES-256 + PBKDF2 şifreleme (varsa)')
            aes_encrypted = None
            aes_key = None
            if AESEncryptor.is_available():
                aes_encrypted, aes_key = AESEncryptor.encrypt(crypto_data)
                if aes_encrypted:
                    logger.info('AES-256 + PBKDF2 şifreleme başarılı')
                    crypto_data = aes_encrypted
                else:
                    logger.warning('AES şifreleme başarısız, önceki katmanda devam ediliyor')
            else:
                logger.info('pycryptodome yok, XOR ile devam (pip install pycryptodome önerilir)')

            logger.info('Ultimate Adım 14: Multi-layer XOR cascade')
            xor_data, xor_keys = self.xor.multi_xor_encode(crypto_data)

            logger.info('Ultimate Adım 15: PolymorphicDecryptor multi-stage şifreleme')
            poly_encrypted, poly_params = PolymorphicDecryptor.generate_multi_stage(xor_data)
            logger.info(f'  Polymorphic şifreleme tamamlandı — rot={poly_params["rot"]}')

            logger.info('Ultimate Adım 16: Zlib level-9 + Ascii85 + massive padding')
            ascii85_encoded = self.ascii85.encode(poly_encrypted, padding_size=random.randint(1000, 3000))
            compressed = zlib.compress(ascii85_encoded.encode('utf-8'), level=9)

            cython_so_file = None
            native_file    = None

            if use_cython and check_cython():
                logger.info('Ultimate Adım 17: Cython → ninja_cython.so')
                try:
                    cython = CythonCompiler(temp_dir)
                    pyx_file = cython.create_obfuscated_wrapper(nuitka_source, 'ninja_cython')
                    cython_so_file = cython.compile_to_so(pyx_file, 'ninja_cython')
                    if cython_so_file:
                        logger.info(f'Cython .so üretildi: {Path(cython_so_file).name}')
                    else:
                        print('\x1b[93m[!] Cython derleme başarısız\x1b[0m')
                except Exception as _ce:
                    print(f'\x1b[93m[!] Cython adımı atlandı: {_ce}\x1b[0m')

            if use_nuitka and check_nuitka():
                try:
                    if cython_so_file and os.path.exists(cython_so_file):
                        logger.info('Ultimate Adım 18: Nuitka → Cython .so embed (so içinde so)')
                        cython_mod = Path(cython_so_file).name.split('.')[0]
                        wrapper_src = f"""import sys as _s, os as _o
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import {cython_mod} as _c
def run(): _c.run()
if __name__ == '__main__': run()
"""
                        wrapper_py = os.path.join(temp_dir, 'ninja_nuitka.py')
                        with open(wrapper_py, 'w', encoding='utf-8') as f:
                            f.write(wrapper_src)
                        nuitka = NuitkaCompiler(temp_dir)
                        native_file = nuitka.compile_with_embedded_cython(wrapper_py, cython_so_file)
                        if native_file:
                            logger.info(f'Nuitka embed .so üretildi: {Path(native_file).name}')
                        else:
                            print('\x1b[93m[!] Nuitka embed başarısız, direkt derleme deneniyor...\x1b[0m')
                            temp_py = os.path.join(temp_dir, 'ninja_native.py')
                            with open(temp_py, 'w', encoding='utf-8') as f:
                                f.write(nuitka_source)
                            native_file = nuitka.compile_module(temp_py)
                    else:
                        logger.info('Ultimate Adım 18: Nuitka direkt derleme (Cython yok)')
                        temp_py = os.path.join(temp_dir, 'ninja_native.py')
                        with open(temp_py, 'w', encoding='utf-8') as f:
                            f.write(nuitka_source)
                        nuitka = NuitkaCompiler(temp_dir)
                        native_file = nuitka.compile_module(temp_py)
                except Exception as _ne:
                    print(f'\x1b[93m[!] Nuitka adımı atlandı: {_ne}\x1b[0m')

            if not native_file and cython_so_file and os.path.exists(cython_so_file):
                native_file = cython_so_file
                logger.info('Native katman: Cython .so (Nuitka embed başarısız)')
            elif native_file:
                logger.info(f'Native katman: Nuitka embedded .so (Cython içinde)')
            else:
                logger.info('Native katman yok (Cython ve Nuitka bulunamadı/başarısız)')

            if native_file and os.path.exists(native_file):
                logger.info('Ultimate Adım 19: ELFProtector (DWARF poison + Fake sym)')
                native_file = ELFProtector.protect(native_file, do_text_encrypt=False)
            else:
                logger.info('Ultimate Adım 19: ELFProtector atlandı (native yok)')

            final_data = compressed

            logger.info('Ultimate Adım 19b: Base64 encoding')
            final_b64 = base64.b64encode(final_data).decode('ascii')
            logger.info('Ultimate Adım 19c: 16 parçaya bölme')
            chunk_size = len(final_b64) // 16
            parts = [final_b64[i * chunk_size:(i + 1) * chunk_size] for i in range(15)]
            parts.append(final_b64[15 * chunk_size:])
            logger.info('Ultimate Adım 19d: Hyperion obfuscation (fake class camouflage)')
            var_names = [self.hyperion._randvar() for _ in range(25)]
            func_names = [self.hyperion._randvar() for _ in range(12)]
            aes_decrypt_code = ''
            if aes_encrypted and aes_key:
                aes_key_b64 = base64.b64encode(aes_key).decode('ascii')
                runtime_key_code = AESEncryptor.derive_runtime_key_code(aes_key_b64)
                runtime_key_fn = re.search(r'def (\w+)\(\)', runtime_key_code).group(1)
                runtime_key_b64 = base64.b64encode(runtime_key_code.encode()).decode('ascii')
                aes_decrypt_code = f"""exec(base64.b64decode('{runtime_key_b64}').decode())
import hashlib as _hl
from Crypto.Cipher import AES as _AES
from Crypto.Util.Padding import unpad as _unpad
_MAGIC = b'NJNC'
if {var_names[1]}[:4] == _MAGIC:
    try:
        _salt = {var_names[1]}[4:20]
        _iters = int.from_bytes({var_names[1]}[20:24], byteorder='big')
        _iv = {var_names[1]}[24:40]
        _ct = {var_names[1]}[40:]
        _pw = {runtime_key_fn}()
        _dk = _hl.pbkdf2_hmac('sha256', _pw, _salt, _iters, dklen=32)
        {var_names[1]} = _unpad(_AES.new(_dk, _AES.MODE_CBC, _iv).decrypt(_ct), _AES.block_size)
        del _salt, _iters, _iv, _ct, _pw, _dk
    except:
        {var_names[1]} = {var_names[1]}[4:].decode('utf-8')
else:
    {var_names[1]} = {var_names[1]}.decode('utf-8')
"""
            marshal_bypass_code = AntiDebug.generate_marshal_bypass()
            marshal_fn = re.search(r'def (\w+)\(_data\)', marshal_bypass_code).group(1)
            marshal_b64 = base64.b64encode(marshal_bypass_code.encode()).decode('ascii')
            pyc_xor_key = random.randint(1, 255)

            poly_xor_dec2 = PolymorphicDecryptor.generate(
                var_names[1], f'bytes([{xor_keys[2]}])*len({var_names[1]})', var_names[2])
            poly_xor_dec3 = PolymorphicDecryptor.generate(
                var_names[2], f'bytes([{xor_keys[1]}])*len({var_names[2]})', var_names[3])
            poly_xor_dec4 = PolymorphicDecryptor.generate(
                var_names[3], f'bytes([{xor_keys[0]}])*len({var_names[3]})', var_names[4])

            poly_key1_b64 = poly_params['key1']
            poly_key2_b64 = poly_params['key2']
            poly_rot      = poly_params['rot']
            poly_unrot    = 8 - poly_rot
            poly_dec_code = PolymorphicDecryptor.generate_multi_stage_decrypt(
                var_names[10], poly_params, var_names[10] + '_dec')

            chacha_decrypt = ''
            if chacha_encrypted and chacha_key:
                chacha_key_b64 = base64.b64encode(chacha_key).decode('ascii')
                chacha_decrypt = ChaCha20Encryptor.generate_decrypt_code(
                    var_names[1], f"'{chacha_key_b64}'", var_names[1] + '_cc')
                chacha_swap = f"{var_names[1]} = {var_names[1]}_cc"
            else:
                chacha_swap = ''

            exec_code = f"""
import base64, zlib, marshal, tempfile, os, sys, shutil, atexit, hashlib, time

exec(base64.b64decode('{marshal_b64}').decode())

{var_names[0]} = DATACONCAT
{var_names[1]} = base64.b64decode({var_names[0]}.encode())
{aes_decrypt_code}
{chacha_decrypt}
{chacha_swap}
{var_names[2]} = bytes(b ^ {xor_keys[2]} for b in {var_names[1]})
{var_names[3]} = bytes(b ^ {xor_keys[1]} for b in {var_names[2]})
{var_names[4]} = bytes(b ^ {xor_keys[0]} for b in {var_names[3]})
{var_names[5]} = zlib.decompress({var_names[4]}).decode()
{var_names[6]} = {var_names[5]}.replace('\\n', '')
{var_names[7]} = base64.a85decode({var_names[6]}.encode())
{var_names[8]} = base64.b64decode({var_names[7]})
{var_names[9]} = int.from_bytes({var_names[8]}[0:4], byteorder='big')
{var_names[10]} = {var_names[8]}[4:4+{var_names[9]}]

import base64 as _pd_b64
_pd_k2 = _pd_b64.b64decode('{poly_key2_b64}')
_pd_s3 = bytes({var_names[10]}[_i] ^ _pd_k2[_i % len(_pd_k2)] for _i in range(len({var_names[10]})))
_pd_s2 = bytes(((b >> {poly_rot}) | (b << {poly_unrot})) & 0xFF for b in _pd_s3)
_pd_k1 = _pd_b64.b64decode('{poly_key1_b64}')
{var_names[10]} = bytes(_pd_s2[_i] ^ _pd_k1[_i % len(_pd_k1)] for _i in range(len(_pd_s2)))
del _pd_s3, _pd_s2, _pd_k1, _pd_k2

{var_names[11]} = tempfile.mkdtemp(prefix=base64.b64decode(b'dG1wXw==').decode())
{var_names[12]} = os.path.join({var_names[11]}, hashlib.sha1(str(time.time()).encode()).hexdigest()[:12])

def {func_names[0]}():
    if os.path.exists({var_names[11]}):
        shutil.rmtree({var_names[11]}, ignore_errors=True)

atexit.register({func_names[0]})

_native_name = 'NATIVE_PLACEHOLDER'
if _native_name and os.path.exists(os.path.join({var_names[11]}, _native_name)):
    import importlib.util as _ilu
    _sp = os.path.join({var_names[11]}, _native_name)
    os.chmod(_sp, 0o755)
    _spec = _ilu.spec_from_file_location('_ninja_mod', _sp)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    if hasattr(_mod, 'run'): _mod.run()
    {func_names[0]}()
else:
    _xk = {pyc_xor_key}
    _raw_pyc = bytes(b ^ _xk for b in {var_names[10]})
    del _xk

    import io as _io
    _buf2 = _io.BytesIO(_raw_pyc)
    _buf2.read(16)
    {var_names[13]} = {marshal_fn}(_buf2.read())
    del _raw_pyc, _buf2

    exec({var_names[13]}, {{'__name__': '__main__', '__file__': '<ninja>', '__builtins__': __builtins__}})
    {func_names[0]}()
"""
            native_fname = Path(native_file).name if native_file and os.path.exists(native_file) else ''
            logger.info('Ultimate Adım 22: Anti-debug inject (ZIP içinde, düzenlenemez)')

            final_code = obf_source
            comprehensive_imports = """import random
import sys
import hashlib
import os
import time
import platform
import struct
import marshal
import zlib
import base64
import tempfile
import shutil
"""
            final_code = comprehensive_imports + final_code
            ult_main, ult_enc, ult_keys = self.main_generator.generate_with_payload(final_code, native_fname=native_fname)

            logger.info('Ultimate Adım 20: LazyChunkEncoder → __s0-4__.bin (zincir key)')
            lazy_chunks, lazy_base_key = LazyChunkEncoder.encode(ult_enc)
            logger.info(f'  LazyChunk: {len(lazy_chunks)} parça, base_key=0x{lazy_base_key:02x}')

            # Veri LazyChunk+XOR pipeline'dan gelir — VM kendi içinde saklamaz
            logger.info('Ultimate Adım 21: MiniVMGenerator → runtime VM program (pipeline modu)')
            vm_prog_bytes = MiniVMGenerator.compile_runtime_program()
            vm_prog_b64   = base64.b64encode(vm_prog_bytes).decode('ascii')
            logger.info(f'  VM program: {len(vm_prog_bytes)} byte (DECOMP+MARSHAL+EXEC+WIPE)')

            # generate_v8: LazyChunk + MiniVM destekli __main__.py
            ult_main_v8 = self.main_generator.generate_v8(
                xor_keys    = ult_keys,
                has_native  = bool(native_fname),
                native_fname= native_fname,
                lazy_base_key = lazy_base_key,
                vm_prog_b64 = vm_prog_b64,
            )

            logger.info('Ultimate Adım 23: Hardware fingerprint key')
            hw_derive_code = HardwareFingerprintKey.generate_derive_code()
            ult_main_v8 = hw_derive_code + '\n' + ult_main_v8

            logger.info('Ultimate Adım 24: Whitespace steganografi')
            try:
                wss_payload = hashlib.sha256(ult_enc[:256] if len(ult_enc) >= 256 else ult_enc).digest()
                ult_main_v8 = WhitespaceSteganography.encode(wss_payload, ult_main_v8)
                logger.info('Whitespace stego uygulandı')
            except Exception as _e:
                logger.warning(f'Whitespace stego atlandı: {_e}')

            logger.info('Ultimate Adım 25: ZIP wrapper (__s0-4__.bin + native + tuzaklar)')
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('__main__.py', ult_main_v8)
                for _ci, _chunk in enumerate(lazy_chunks):
                    zf.writestr(f'__s{_ci}__.bin', _chunk)
                    logger.info(f'  __s{_ci}__.bin: {len(_chunk)} byte')
                # Native .so
                if native_file and os.path.exists(native_file):
                    zf.write(native_file, Path(native_file).name)
                    logger.info(f'  Native binary: {Path(native_file).name}')
                FakeSoGenerator.add_to_zip(zf, count=2)
                fake_pyc = bytes([0x0d, 0x0a, 0x00, 0x00]) + os.urandom(random.randint(512, 2048))
                zf.writestr('_cache.pyc', fake_pyc)
                # Sahte __script__.bin tuzağı (içi çöp — birini yanıltır)
                zf.writestr('__script__.bin', os.urandom(random.randint(256, 512)))
                logger.info('  Sahte .pyc + __script__.bin tuzakları eklendi')

            logger.info('Ultimate Adım 26: ZIP → base64 wrapper')
            zip_bytes = zip_buffer.getvalue()
            b64_zip = base64.b64encode(zip_bytes).decode('ascii')
            final_wrapper = self._generate_ninjapy_wrapper(b64_zip)

            logger.info('Ultimate Adım 27: Tamamlandı (v8 — 27 katman + ELF + LazyChunk + MiniVM)')
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_wrapper)
            logger.info(f'Ultimate v8 encoding tamamlandı: {output_file}')
            return output_file
        finally:
            try:
                for _ in range(3):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        if not os.path.exists(temp_dir):
                            break
                    except:
                        pass
            except:
                pass

    def _generate_cython_loader(self, so_b64, aes_key_b64=None):
        hyp = self.hyperion
        v = [hyp._randvar() for _ in range(12)]
        aes_block = ''
        if aes_key_b64:
            aes_block = f'''
import hashlib as _hl
from Crypto.Cipher import AES as _AES
from Crypto.Util.Padding import unpad as _unpad
_raw = base64.b64decode({v[0]})
_pw = base64.b64decode('{aes_key_b64}')
_salt = _raw[4:20]; _iters = int.from_bytes(_raw[20:24], 'big')
_iv = _raw[24:40]; _ct = _raw[40:]
_dk = _hl.pbkdf2_hmac('sha256', _pw, _salt, _iters, dklen=32)
{v[6]} = _unpad(_AES.new(_dk, _AES.MODE_CBC, _iv).decrypt(_ct), _AES.block_size)
del _pw, _salt, _iters, _iv, _ct, _dk, _raw
'''
        else:
            aes_block = f'{v[6]} = base64.b64decode({v[0]})'
        return f'''import base64, tempfile, os, sys, shutil, atexit, importlib.util
{v[0]} = "{so_b64}"
{v[1]} = tempfile.mkdtemp(prefix='ninja_cy_')
def {v[2]}():
    if os.path.exists({v[1]}): shutil.rmtree({v[1]}, ignore_errors=True)
atexit.register({v[2]})
{aes_block}
{v[3]} = os.path.join({v[1]}, 'ninja_core.so')
with open({v[3]}, 'wb') as f: f.write({v[6]})
os.chmod({v[3]}, 0o755)
{v[4]} = importlib.util.spec_from_file_location('ninja_core', {v[3]})
{v[5]} = importlib.util.module_from_spec({v[4]})
sys.modules['ninja_core'] = {v[5]}
{v[4]}.loader.exec_module({v[5]})
{v[5]}.run()
{v[2]}()
'''

    def _generate_nuitka_loader(self, binary_b64, binary_name):
        hyp = self.hyperion
        vars = [hyp._randvar() for _ in range(10)]
        return f"""#!/usr/bin/env python3\nimport base64, tempfile, os, sys, shutil, atexit, importlib.util\n\n{vars[0]} = "{binary_b64}"\n{vars[1]} = tempfile.mkdtemp(prefix='ninja_nk_')\n\ndef {vars[2]}():\n    if os.path.exists({vars[1]}):\n        shutil.rmtree({vars[1]}, ignore_errors=True)\n\natexit.register({vars[2]})\n\n{vars[3]} = os.path.join({vars[1]}, '{binary_name}')\nwith open({vars[3]}, 'wb') as f:\n    f.write(base64.b64decode({vars[0]}))\n\n{vars[4]} = importlib.util.spec_from_file_location('ninja_main', {vars[3]})\n{vars[5]} = importlib.util.module_from_spec({vars[4]})\nsys.modules['ninja_main'] = {vars[5]}\n{vars[4]}.loader.exec_module({vars[5]})\n{vars[2]}()\n"""

    def _generate_advanced_wrapper(self, parts, var_names, func_names):
        return f'''#!/usr/bin/env python3\nimport base64,tempfile,os,sys,zlib,random,hashlib,time,marshal,types,shutil,atexit\n\ndef {func_names[0]}():\n    {var_names[0]}=[random.randint(0,9999)for _ in range(3000)]\n    {var_names[1]}=sum({var_names[0]})%999999\n    {var_names[2]}=hashlib.sha256(str({var_names[1]}).encode()).hexdigest()\n    return len({var_names[2]})>50\n\ndef {func_names[1]}():\n    {var_names[3]}=b"anti_debug"*500\n    {var_names[4]}=zlib.compress({var_names[3]})\n    return len(zlib.decompress({var_names[4]}))>4000\n\ndef {func_names[2]}():\n    return int(hashlib.md5(b"check").hexdigest(),16)%1000000>0\n\n{var_names[5]}_p1="{parts[0]}"\n{var_names[5]}_p2="{parts[1]}"\n{var_names[5]}_p3="{parts[2]}"\n{var_names[5]}_p4="{parts[3]}"\n\ndef {func_names[3]}():\n    if not({func_names[0]}()and {func_names[1]}()and {func_names[2]}()):return None\n    try:\n        {var_names[6]}={var_names[5]}_p1+{var_names[5]}_p2+{var_names[5]}_p3+{var_names[5]}_p4\n        {var_names[7]}=zlib.decompress(base64.b64decode({var_names[6]}.encode()))\n        {var_names[8]}=int.from_bytes({var_names[7]}[0:4],byteorder='big')\n        return {var_names[7]}[4:4+{var_names[8]}].decode('utf-8')\n    except:return None\n\n{var_names[9]}=tempfile.mkdtemp(prefix='ninja_')\n\ndef _clean():\n    if os.path.exists({var_names[9]}):shutil.rmtree({var_names[9]},ignore_errors=True)\n\natexit.register(_clean)\n\ndef {func_names[4]}():\n    {var_names[6]}={func_names[3]}()\n    if {var_names[6]} is None:sys.exit(1)\n    try:\n        import base64 as b64\n        clean={var_names[6]}.replace('\\n','')\n        d1=b64.a85decode(clean.encode())\n        d2=b64.b64decode(d1)\n        sz=int.from_bytes(d2[0:4],byteorder='big')\n        pyc=d2[4:4+sz]\n        pf=os.path.join({var_names[9]},'m.pyc')\n        with open(pf,'wb')as f:f.write(pyc)\n        with open(pf,'rb')as f:\n            f.read(16)\n            co=marshal.load(f)\n        exec(co,{{'__name__':'__main__','__file__':pf,'__builtins__':__builtins__}})\n    except Exception as e:\n        import sys as _sys\n        print(f"[!] Hata ({{type(e).__name__}}): {{e}}", file=_sys.stderr)\n        import traceback; traceback.print_exc()\n    finally:_clean()\n\nif __name__=="__main__":{func_names[4]}()\n'''

    def _generate_ninjapy_wrapper(self, b64_data):
        py_ver = sys.version_info[:2]
        return f"""Bugra='.BugraPy'\nimport os,sys,base64 as B,tempfile as T\n\n_ENC_VER = {py_ver}\n_CUR_VER = (sys.version_info.major, sys.version_info.minor)\nif _CUR_VER != _ENC_VER:\n    print(f"[!] UYARI: Bu dosya Python {{_ENC_VER[0]}}.{{_ENC_VER[1]}} ile şifrelendi.")\n    print(f"    Mevcut Python: {{_CUR_VER[0]}}.{{_CUR_VER[1]}}")\n    print(f"    Bytecode uyumsuzluğu nedeniyle çalışmayabilir!")\n\nC='{b64_data}'\nA=os.path.join(T.gettempdir(),Bugra)\n\ndef _d():\n    for _ in range(3):\n        try:\n            if os.path.exists(A):os.remove(A)\n            break\n        except:pass\n\ntry:\n    with open(A,'wb')as D:D.write(B.b64decode(C))\n    os.chmod(A,0o700)\n    import subprocess\n    r=subprocess.run([sys.executable,A]+sys.argv[1:],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr)\n    _d()\n    sys.exit(r.returncode)\nexcept Exception as E:\n    _d()\n    print(f"[!] Çalıştırma hatası ({{type(E).__name__}}): {{E}}",file=sys.stderr)\n    import traceback;traceback.print_exc()\n    sys.exit(1)\nfinally:\n    _d()\n"""

    def _generate_ninjapy_wrapper_png(self, png_b64: str, xor_key: int):
        py_ver = sys.version_info[:2]
        inner = (
            "Bugra='.BugraPy'\n"
            "import os,sys,base64 as _B,tempfile as _T,struct as _pst,zlib as _pzl\n"
            f"_ENC_VER={py_ver}\n"
            "_CUR_VER=(sys.version_info.major,sys.version_info.minor)\n"
            "if _CUR_VER!=_ENC_VER:\n"
            '    print(f"[!] UYARI: Python {_ENC_VER[0]}.{_ENC_VER[1]} ile sifrelendi")\n'
            f"_PNG=_B.b64decode('{png_b64}')\n"
            f"_XK={xor_key}\n"
            "_pp=8;_pidat=b'';_pw=_ph=0;_pxk=None\n"
            "while _pp<len(_PNG)-12:\n"
            "    _pln=_pst.unpack('>I',_PNG[_pp:_pp+4])[0]\n"
            "    _pct=_PNG[_pp+4:_pp+8];_pdt=_PNG[_pp+8:_pp+8+_pln];_pp+=12+_pln\n"
            "    if _pct==b'IHDR':_pw,_ph=_pst.unpack('>II',_pdt[:8])\n"
            "    elif _pct==b'tEXt':\n"
            "        _pts=_pdt.split(b'\\x00')\n"
            "        if len(_pts)>=2 and _pts[1]:_pxk=_pts[1][0]^0xA5\n"
            "    elif _pct==b'IDAT':_pidat+=_pdt\n"
            "    elif _pct==b'IEND':break\n"
            "_prw=_pzl.decompress(_pidat);_prb=_pw*3\n"
            "_pca=bytearray()\n"
            "for _pri in range(_ph):\n"
            "    _ps=_pri*(_prb+1)+1;_pca.extend(_prw[_ps:_ps+_prb])\n"
            "_pbi=[_b&1 for _b in _pca];_pex=bytearray()\n"
            "for _pi in range(0,len(_pbi)-7,8):\n"
            "    _byte=0\n"
            "    for _pj in range(8):_byte=(_byte<<1)|_pbi[_pi+_pj]\n"
            "    _pex.append(_byte)\n"
            "_pdl=_pst.unpack('>I',bytes(_pex[:4]))[0]\n"
            "_zip_bytes=bytes(_b^(_pxk or _XK) for _b in _pzl.decompress(bytes(_pex[4:4+_pdl])))\n"
            "del _PNG,_prw,_pca,_pbi,_pex,_pidat\n"
            "A=os.path.join(_T.gettempdir(),Bugra)\n"
            "def _d():\n"
            "    for _ in range(3):\n"
            "        try:\n"
            "            if os.path.exists(A):os.remove(A)\n"
            "            break\n"
            "        except:pass\n"
            "try:\n"
            "    with open(A,'wb')as D:D.write(_zip_bytes)\n"
            "    del _zip_bytes\n"
            "    os.chmod(A,0o700)\n"
            "    import subprocess\n"
            "    r=subprocess.run([sys.executable,A]+sys.argv[1:],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr)\n"
            "    _d();sys.exit(r.returncode)\n"
            "except Exception as E:\n"
            "    _d()\n"
            '    print(f"[!] Hata ({type(E).__name__}): {E}",file=sys.stderr)\n'
            "    sys.exit(1)\n"
            "finally:\n"
            "    _d()\n"
        )
        return inner

    def decode_file(self, input_file, output_file=None):
        if output_file is None:
            base = os.path.splitext(input_file)[0]
            if base.endswith('_enc'):
                base = base[:-4]
            output_file = f'{base}_decoded.py'
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search("C='([A-Za-z0-9+/=]+)'", content)
        if not match:
            raise ValueError('Base64 data bulunamadı')
        zip_data = base64.b64decode(match.group(1))
        zip_buffer = BytesIO(zip_data)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            if '__script__.py' in zf.namelist():
                source = zf.read('__script__.py').decode('utf-8')
            else:
                raise ValueError('Script bulunamadı')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(source)
        return output_file

def show_file_info(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    print(S + f'[*] Dosya: {B}{filepath}')
    print(S + f'[*] Boyut: {B}{os.path.getsize(filepath):,} bytes')
    match = re.search("C='([A-Za-z0-9+/=]+)'", content)
    if match:
        b64 = match.group(1)
        print(S + f'[*] Base64: {B}{len(b64):,} chars')
        zip_data = base64.b64decode(b64)
        print(S + f'[*] ZIP: {B}{len(zip_data):,} bytes')
        with zipfile.ZipFile(BytesIO(zip_data), 'r') as zf:
            print(S + '\n[*] ZIP İçeriği:')
            for info in zf.infolist():
                r = info.compress_size / info.file_size if info.file_size > 0 else 0
                print(f'    - {info.filename}: {info.file_size:,} bytes (sıkıştırma: {r:.1%})')

def show_system_info():
    G = '\x1b[32m'; Y = '\x1b[93m'; B = '\x1b[96m'; R = '\x1b[31m'; X = '\x1b[0m'; D = '\x1b[2m'
    print(f"""
{G}  ███╗   ██╗██╗███╗   ██╗     ██╗ █████╗
{G}  ████╗  ██║██║████╗  ██║     ██║██╔══██╗
{G}  ██╔██╗ ██║██║██╔██╗ ██║     ██║███████║
{G}  ██║╚██╗██║██║██║╚██╗██║██   ██║██╔══██║
{G}  ██║ ╚████║██║██║ ╚████║╚█████╔╝██║  ██║
{G}  ╚═╝  ╚═══╝╚═╝╚═╝  ╚═══╝ ╚════╝ ╚═╝  ╚═╝{X}
{D}  ─────────────────────────────────────────{X}
  {Y}NinjaEnc v4.0{X}  {D}by{X} {G}Buğra{X}   {D}Python Obfuscator{X}
{D}  ─────────────────────────────────────────{X}""")
    layers = [
        "Integrity Check v2",
        "Anti-Debug Pro v2",
        "Anti-Frida v3",
        "Timing Anti-Debug",
        "SIGTRAP Trap",
        "Exec/Marshal/Compile Guard",
        "GC Object Scan v2",
        "Parent Process Check v2",
        "Dead Code Injection",
        "Opaque Predicates v2",
        "MBA Transform v2",
        "Nuitka Hardened v3",
        "ELFProtector (Faz 3)",
        "LazyChunk 5-Part (Faz 4)",
        "MiniVM Dispatcher (Faz 4)",
        "Anti-Reverse Maps",
        "exec() Hook Guard v2",
        "marshal.loads Guard",
        "compile() Hook Guard",
        "ctypes PyEval Bypass",
        "Memory Wipe",
        "Memory-Only Exec",
        "Custom Marshal Bypass",
        "AES Runtime Key",
        "String Table Encrypt",
        "Control Flow Flatten",
        "AST Obfuscation v2",
        "AES-256 + PBKDF2",
        "Multi-Layer XOR",
        "Zlib + Ascii85",
        "ZIP Binary Wrapper",
    ]
    print(f"\n  {B}Aktif Koruma Katmanları{X}  {D}({len(layers)} katman){X}\n")
    col = 2
    rows = (len(layers) + col - 1) // col
    for i in range(rows):
        left  = f"  {G}✦{X} {Y}{layers[i]}{X}"
        right_idx = i + rows
        right = f"  {G}✦{X} {Y}{layers[right_idx]}{X}" if right_idx < len(layers) else ''
        print(f"{left:<55}{right}")
    print()

def interactive_mode():
    show_system_info()
    G = '\x1b[32m'; Y = '\x1b[93m'; B = '\x1b[96m'; X = '\x1b[0m'; D = '\x1b[2m'
    print(f"  {B}Encoding Modları{X}\n")
    print(f"  {G}1{X}  {Y}Basit       {X}  {D}ZIP + Base64{X}")
    print(f"  {G}2{X}  {Y}Gelişmiş    {X}  {D}Bytecode + Ascii85 + Zlib{X}")
    print(f"  {G}3{X}  {Y}Cython      {X}  {D}Native .so derleme{X}")
    print(f"  {G}4{X}  {Y}Nuitka      {X}  {D}C++ native derleme{X}")
    print(f"  {G}5{X}  {Y}Hyperion    {X}  {D}Variable rename + fake class{X}")
    print(f"  {G}6{X}  {Y}ULTIMATE    {X}  {D}31 katman — maksimum koruma{X}")
    print()

    print()
    while True:
        input_file = input(S + 'Encode edilecek Python dosyasının yolunu gir: ' + B).strip()
        if not input_file:
            print(K + '[!] Bir dosya yolu gir!')
            continue
        if not os.path.exists(input_file):
            print(K + f'[!] Dosya bulunamadı: {input_file}')
            continue
        if not input_file.endswith('.py'):
            print(K + '[!] Bir Python (.py) dosyası seç!')
            continue
        break
    while True:
        mode = input(S + '\nEncoding modu seç (1/2/3/4/5/6) [varsayılan: 6]: ').strip() or '6'
        if mode in ['1', '2', '3', '4', '5', '6']:
            break
        print(K + '[!] Geçersiz seçim!')
    base_name = os.path.splitext(input_file)[0]
    output_file = f'{base_name}_enc.py'
    mode_names = {'1': 'Basit', '2': 'Gelişmiş', '3': 'Cython', '4': 'Nuitka', '5': 'Hyperion', '6': 'ULTIMATE'}
    print(S + f'\n[*] Input: {B}{input_file}')
    print(S + f'[*] Output: {B}{output_file}')
    print(S + f'[*] Mod: {B}{mode_names[mode]}')
    print('\n' + '-' * 40)
    try:
        encoder = NinjaEncoder()
        if mode == '1':
            result = encoder.encode_simple(input_file, output_file)
        elif mode == '2':
            result = encoder.encode_advanced(input_file, output_file)
        elif mode == '3':
            result = encoder.encode_cython(input_file, output_file)
        elif mode == '4':
            result = encoder.encode_nuitka(input_file, output_file)
        elif mode == '5':
            result = encoder.encode_hyperion(input_file, output_file)
        elif mode == '6':
            result = encoder.encode_ultimate(input_file, output_file)
        else:
            result = encoder.encode_ultimate(input_file, output_file)
        print('-' * 40)
        print(Y + '\n[+] Encoding başarıyla tamamlandı!')
        input_size = os.path.getsize(input_file)
        output_size = os.path.getsize(result)
        print(S + f'[*] Input boyutu:  {B}{input_size:,} bytes')
        print(S + f'[*] Output boyutu: {B}{output_size:,} bytes')
        print(S + f'[*] Oran: {B}{output_size / input_size:.2f}x')
        print(S + f'\n[*] Çalıştırmak için: python3 {result}')
    except KeyboardInterrupt:
        print(K + '\n\n[!] İşlem iptal edildi.')
        sys.exit(1)
    except Exception as e:
        print(K + f'\n[!] Hata: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='NinjaEnc v4.0 - Ultimate Python Code Protector (Pydroid3 Uyumlu)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='\nÖrnekler:\n  python3 ninjaEnc.py                           # Interactive mod\n  python3 ninjaEnc.py script.py                 # Basit encoding\n  python3 ninjaEnc.py script.py --cython        # Cython native derleme\n  python3 ninjaEnc.py script.py --nuitka        # Nuitka C++ derleme\n  python3 ninjaEnc.py script.py --hyperion      # Hyperion obfuscation\n  python3 ninjaEnc.py script.py --ultimate      # 24 katmanlı maksimum\n  python3 ninjaEnc.py script.py --seed 12345    # Tekrarlanabilir çıktı\n  python3 ninjaEnc.py --decode encoded.py       # Decode et\n  python3 ninjaEnc.py --info encoded.py         # Bilgi göster\n  python3 ninjaEnc.py --sysinfo                 # Sistem bilgisi\n'
    )
    parser.add_argument('input', nargs='?', help='Input Python dosyası')
    parser.add_argument('-o', '--output', help='Output dosya adı')
    parser.add_argument('--advanced', action='store_true', help='7 adımlı gelişmiş encoding')
    parser.add_argument('--cython', action='store_true', help='Cython native .so derleme')
    parser.add_argument('--nuitka', action='store_true', help='Nuitka C++ native derleme')
    parser.add_argument('--hyperion', action='store_true', help='Hyperion obfuscation')
    parser.add_argument('--ultimate', action='store_true', help='24 katmanlı maksimum koruma')

    parser.add_argument('--decode', action='store_true', help='Decode et')
    parser.add_argument('--info', action='store_true', help='Dosya bilgisi göster')
    parser.add_argument('--sysinfo', action='store_true', help='Sistem bilgisi göster')
    parser.add_argument('--seed', type=int, default=None,
                        help='Obfuscation seed — aynı seed → aynı çıktı (varsayılan: rastgele)')
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        print(S + f'[*] Obfuscation seed: {B}{args.seed}{S} (deterministik mod)')
    else:
        random.seed()

    if args.sysinfo:
        show_system_info()
        return
    if not args.input:
        interactive_mode()
        return
    encoder = NinjaEncoder()
    if args.info:
        show_file_info(args.input)
    elif args.decode:
        output = encoder.decode_file(args.input, args.output)
        print(S + f'[+] Decoded: {B}{output}')
    else:
        if args.ultimate:
            output = encoder.encode_ultimate(args.input, args.output, seed=args.seed)
        elif args.nuitka:
            output = encoder.encode_nuitka(args.input, args.output)
        elif args.cython:
            output = encoder.encode_cython(args.input, args.output)
        elif args.hyperion:
            output = encoder.encode_hyperion(args.input, args.output)
        elif args.advanced:
            output = encoder.encode_advanced(args.input, args.output)
        else:
            output = encoder.encode_simple(args.input, args.output)
        print(S + f'[+] Encoded: {B}{output}')
        input_size = os.path.getsize(args.input)
        output_size = os.path.getsize(output)
        print(S + f'[*] Input:  {B}{input_size:,} bytes')
        print(S + f'[*] Output: {B}{output_size:,} bytes')
        print(S + f'[*] Oran: {B}{output_size / input_size:.2f}x')
        if args.seed is not None:
            print(S + f'[*] Seed:   {B}{args.seed}{S} — aynı seed ile aynı çıktı üretilir')
if __name__ == '__main__':
    main()
