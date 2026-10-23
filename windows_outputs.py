"""Windows handle-relative output IO. No path-based staging, rename or cleanup.

NtCreateFile resolves one leaf relative to an already verified directory handle.
NtSetInformationFile renames the held staging-file object relative to that handle.
https://learn.microsoft.com/windows/win32/api/winternl/nf-winternl-ntcreatefile
https://learn.microsoft.com/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information
"""
import ctypes as C
from ctypes import wintypes as W
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import os
import uuid


class UnicodeString(C.Structure):
    _fields_ = [('length', W.USHORT), ('maximum', W.USHORT), ('buffer', W.LPWSTR)]


class ObjectAttributes(C.Structure):
    _fields_ = [('length', W.ULONG), ('root', W.HANDLE), ('name', C.POINTER(UnicodeString)),
                ('attributes', W.ULONG), ('security', C.c_void_p), ('quality', C.c_void_p)]


class IOStatus(C.Structure):
    _fields_ = [('status', C.c_void_p), ('information', C.c_size_t)]


class FileInfo(C.Structure):
    _fields_ = [('attributes', W.DWORD), ('creation', W.FILETIME), ('access', W.FILETIME), ('write', W.FILETIME),
                ('volume', W.DWORD), ('size_high', W.DWORD), ('size_low', W.DWORD), ('links', W.DWORD),
                ('index_high', W.DWORD), ('index_low', W.DWORD)]


class RenameInfo(C.Structure):
    _fields_ = [('replace', W.BOOLEAN), ('root', W.HANDLE), ('length', W.DWORD), ('name', W.WCHAR * 1)]


@lru_cache(maxsize=1)
def api():
    kernel = C.WinDLL('kernel32', use_last_error=True); native = C.WinDLL('ntdll')
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]; kernel.CloseHandle.restype = W.BOOL
    kernel.GetFileInformationByHandle.argtypes = [W.HANDLE, C.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = W.BOOL
    native.NtCreateFile.argtypes = [C.POINTER(W.HANDLE), W.DWORD, C.POINTER(ObjectAttributes), C.POINTER(IOStatus),
                                   C.c_void_p, W.ULONG, W.ULONG, W.ULONG, W.ULONG, C.c_void_p, W.ULONG]
    native.NtCreateFile.restype = C.c_long
    native.NtSetInformationFile.argtypes = [W.HANDLE, C.POINTER(IOStatus), C.c_void_p, W.ULONG, W.ULONG]
    native.NtSetInformationFile.restype = C.c_long
    native.RtlNtStatusToDosError.argtypes = [C.c_long]; native.RtlNtStatusToDosError.restype = W.ULONG
    return kernel, native


def ntcheck(status):
    if status < 0: raise C.WinError(api()[1].RtlNtStatusToDosError(status))


def info(handle):
    result = FileInfo()
    if not api()[0].GetFileInformationByHandle(handle, C.byref(result)): raise C.WinError(C.get_last_error())
    if result.attributes & 0x400: raise ValueError('Reparse points are not permitted for output IO. Choose the actual folder again.')
    return result


@contextmanager
def directory(folder):
    # OPEN_REPARSE_POINT prevents final-component traversal. No share-delete:
    # selected directory cannot be renamed/deleted during the transaction.
    kernel, _ = api()
    handle = kernel.CreateFileW(folder['path'], 0x001000A3, 3, None, 3, 0x02200000, None)
    if handle == C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
    try:
        value = info(handle)
        if not value.attributes & 0x10 or (value.volume, (value.index_high << 32) | value.index_low) != (folder['device'], folder['inode']):
            raise ValueError('The selected folder was replaced. Choose it again to authorize saving.')
        yield handle
    finally: kernel.CloseHandle(handle)


def relative_file(root, name, create):
    encoded = name.encode('utf-16-le'); buffer = C.create_string_buffer(encoded + b'\0\0')
    text = UnicodeString(len(encoded), len(encoded) + 2, C.cast(buffer, W.LPWSTR))
    attributes = ObjectAttributes(C.sizeof(ObjectAttributes), root, C.pointer(text), 0x40, None, None)
    result, status = W.HANDLE(), IOStatus()
    # CREATE: DELETE + WRITE_DATA + READ_ATTRIBUTES + SYNCHRONIZE, share none.
    # OPEN: READ_DATA + READ_ATTRIBUTES + SYNCHRONIZE, share read only.
    access = 0x00110082 if create else 0x00100081
    ntcheck(api()[1].NtCreateFile(C.byref(result), access, C.byref(attributes), C.byref(status), None,
                                 0x80, 0 if create else 1, 2 if create else 1,
                                 0x00200060, None, 0))  # non-directory, synchronous, open reparse object itself
    try:
        value = info(result)
        if value.attributes & 0x10 or value.links != 1: raise ValueError('Output staging must be a regular unlinked file.')
    except Exception:
        api()[0].CloseHandle(result); raise
    return result


def publish(root, source, name):
    encoded = name.encode('utf-16-le'); offset = RenameInfo.name.offset
    buffer = C.create_string_buffer(offset + len(encoded))
    header = C.cast(buffer, C.POINTER(RenameInfo)).contents
    header.replace = False; header.root = root; header.length = len(encoded)
    C.memmove(C.addressof(buffer) + offset, encoded, len(encoded))
    status = IOStatus()
    ntcheck(api()[1].NtSetInformationFile(source, C.byref(status), buffer, len(buffer), 10))


def discard(source):
    status, delete = IOStatus(), W.BOOLEAN(True)
    ntcheck(api()[1].NtSetInformationFile(source, C.byref(status), C.byref(delete), C.sizeof(delete), 13))


def file_object(handle, mode, flags, delete_on_failure=False):
    """Transfer ownership to Python, closing the exact native handle on errors."""
    import msvcrt
    fd = None
    try:
        fd = msvcrt.open_osfhandle(handle.value, flags)
        return os.fdopen(fd, mode)
    except Exception:
        try:
            if delete_on_failure: discard(handle)
        finally:
            if fd is None: api()[0].CloseHandle(handle)
            else: os.close(fd)
        raise


def write(folder, name, audio):
    with directory(folder) as root:
        handle = relative_file(root, '.localvoice-' + uuid.uuid4().hex + '.partial', True)
        published = False
        with file_object(handle, 'wb', os.O_WRONLY | os.O_BINARY, True) as output:
            try:
                output.write(audio); output.flush(); os.fsync(output.fileno())
                publish(root, handle, name)
                published = True
            finally:
                if not published: discard(handle)


def matches(folder, name, audio):
    with directory(folder) as root:
        try: handle = relative_file(root, name, False)
        except FileNotFoundError: return False
        with file_object(handle, 'rb', os.O_RDONLY | os.O_BINARY) as source:
            value = info(handle)
            if ((value.size_high << 32) | value.size_low) != len(audio): return False
            digest = hashlib.sha256()
            while block := source.read(1024 * 1024): digest.update(block)
            return digest.digest() == hashlib.sha256(audio).digest()
