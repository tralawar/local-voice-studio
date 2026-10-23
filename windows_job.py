"""Windows 10+ process ownership, assigned atomically at CreateProcess time.

The job handle is never inherited. Closing the owner, including TerminateProcess,
closes its last handle and Windows kills the contained children/descendants.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess


class BasicLimits(C.Structure):
    _fields_ = [('ProcessTime', C.c_longlong), ('JobTime', C.c_longlong), ('LimitFlags', W.DWORD),
                ('MinimumWorkingSet', C.c_size_t), ('MaximumWorkingSet', C.c_size_t),
                ('ActiveProcessLimit', W.DWORD), ('Affinity', C.c_size_t),
                ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]


class IOCounters(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ('ReadOperations', 'WriteOperations', 'OtherOperations', 'ReadBytes', 'WriteBytes', 'OtherBytes')]


class ExtendedLimits(C.Structure):
    _fields_ = [('Basic', BasicLimits), ('IO', IOCounters), ('ProcessMemory', C.c_size_t),
                ('JobMemory', C.c_size_t), ('PeakProcessMemory', C.c_size_t), ('PeakJobMemory', C.c_size_t)]


class StartupInfo(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                *[(name, W.DWORD) for name in ('x', 'y', 'width', 'height', 'xchars', 'ychars', 'fill', 'flags')],
                ('show', W.WORD), ('reservedSize', W.WORD), ('reservedBytes', C.POINTER(W.BYTE)),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class StartupInfoEx(C.Structure):
    _fields_ = [('info', StartupInfo), ('attributes', C.c_void_p)]


class ProcessInfo(C.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]


def kernel():
    if os.name != 'nt': raise RuntimeError('Windows Job Objects require Windows 10 or newer.')
    api = C.WinDLL('kernel32', use_last_error=True)
    declarations = {
        'CreateJobObjectW': ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        'SetInformationJobObject': ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'GetCurrentProcess': ([], W.HANDLE),
        'DuplicateHandle': ([W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD], W.BOOL),
        'InitializeProcThreadAttributeList': ([C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)], W.BOOL),
        'UpdateProcThreadAttribute': ([C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p], W.BOOL),
        'DeleteProcThreadAttributeList': ([C.c_void_p], None),
        'CreateProcessW': ([W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(StartupInfoEx), C.POINTER(ProcessInfo)], W.BOOL),
        'GetExitCodeProcess': ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
        'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL)
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(api, name); function.argtypes = arguments; function.restype = result
    return api


def checked(result):
    if not result: raise C.WinError(C.get_last_error())
    return result


class OwnedProcess:
    def __init__(self, api, handle, pid, command):
        self.api, self.handle, self.pid, self.args = api, handle, pid, command
    def poll(self):
        code = W.DWORD(); checked(self.api.GetExitCodeProcess(self.handle, C.byref(code)))
        return None if code.value == 259 else code.value
    def wait(self, timeout=None):
        result = self.api.WaitForSingleObject(self.handle, 0xffffffff if timeout is None else int(timeout * 1000))
        if result == 258: raise subprocess.TimeoutExpired(self.args, timeout)
        if result == 0xffffffff: raise C.WinError(C.get_last_error())
        return self.poll()
    def terminate(self):
        if self.poll() is None: checked(self.api.TerminateProcess(self.handle, 1))
    kill = terminate
    def close(self):
        if self.handle: self.api.CloseHandle(self.handle); self.handle = None


class WindowsJob:
    def __init__(self):
        self.api = kernel(); self.children = []
        self.handle = checked(self.api.CreateJobObjectW(None, None))
        limits = ExtendedLimits(); limits.Basic.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        try: checked(self.api.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)))
        except Exception: self.close(); raise

    def spawn(self, command, *, cwd, env, stdout):
        import msvcrt
        # Explicit handle list prevents the job handle or unrelated handles from
        # reaching a child. JOB_LIST assigns ownership inside CreateProcessW,
        # eliminating a post-spawn assignment/orphan window.
        duplicates = []; attributes = None; initialized = False
        with open(os.devnull, 'rb') as null_input:
            try:
                current = self.api.GetCurrentProcess()
                for source in (null_input, stdout):
                    duplicate = W.HANDLE()
                    checked(self.api.DuplicateHandle(current, msvcrt.get_osfhandle(source.fileno()), current, C.byref(duplicate), 0, True, 2))
                    duplicates.append(duplicate)
                size = C.c_size_t()
                self.api.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
                storage = C.create_string_buffer(size.value)
                attributes = C.cast(storage, C.c_void_p)
                checked(self.api.InitializeProcThreadAttributeList(attributes, 2, 0, C.byref(size)))
                initialized = True
                jobs = (W.HANDLE * 1)(self.handle)
                handles = (W.HANDLE * 2)(duplicates[0].value, duplicates[1].value)
                checked(self.api.UpdateProcThreadAttribute(attributes, 0, 0x2000d, jobs, C.sizeof(jobs), None, None))
                checked(self.api.UpdateProcThreadAttribute(attributes, 0, 0x20002, handles, C.sizeof(handles), None, None))
                startup = StartupInfoEx(); startup.info.cb = C.sizeof(startup); startup.attributes = attributes
                startup.info.flags = 0x100  # STARTF_USESTDHANDLES
                startup.info.stdin = duplicates[0]; startup.info.stdout = startup.info.stderr = duplicates[1]
                process = ProcessInfo()
                environment = C.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(env.items(), key=lambda item: item[0].upper())) + '\0\0')
                line = C.create_unicode_buffer(subprocess.list2cmdline(command))
                checked(self.api.CreateProcessW(str(command[0]), line, None, None, True,
                                               0x08000000 | 0x00080000 | 0x00000400,
                                               environment, str(cwd), C.byref(startup), C.byref(process)))
                self.api.CloseHandle(process.thread)
                child = OwnedProcess(self.api, process.process, process.pid, command)
                self.children.append(child)
                return child
            finally:
                if initialized: self.api.DeleteProcThreadAttributeList(attributes)
                for handle in duplicates: self.api.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None
        for child in self.children:
            try: child.wait(10)
            finally: child.close()
        self.children = []
