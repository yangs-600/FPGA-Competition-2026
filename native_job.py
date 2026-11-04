"""Windows Job Object runner; accepts nonzero exits without treating them as proofs."""
import ctypes as C
from ctypes import wintypes as W
import msvcrt
import os
import subprocess
import time

K = C.WinDLL('kernel32', use_last_error=True)
class Startup(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR)] + [(n,W.DWORD) for n in ('x','y','xs','ys','charsx','charsy','fill','flags')] + [('show',W.WORD),('cbreserved',W.WORD),('lpreserved',C.c_void_p),('stdin',W.HANDLE),('stdout',W.HANDLE),('stderr',W.HANDLE)]
class ProcessInfo(C.Structure):
    _fields_=[('process',W.HANDLE),('thread',W.HANDLE),('pid',W.DWORD),('tid',W.DWORD)]
class BasicLimit(C.Structure):
    _fields_=[('process_time',C.c_longlong),('job_time',C.c_longlong),('flags',W.DWORD),('min_ws',C.c_size_t),('max_ws',C.c_size_t),('active',W.DWORD),('affinity',C.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
class IO(C.Structure):
    _fields_=[(n,C.c_ulonglong) for n in ('read','write','other','readbytes','writebytes','otherbytes')]
class Extended(C.Structure):
    _fields_=[('basic',BasicLimit),('io',IO)]+[(n,C.c_size_t) for n in ('process_memory','job_memory','peak_process_memory','peak_job_memory')]
class Account(C.Structure):
    _fields_=[(n,C.c_longlong) for n in ('user','kernel','perioduser','periodkernel')]+[(n,W.DWORD) for n in ('faults','total','active','terminated')]
def api(name, args, result=W.BOOL):
    f=getattr(K,name); f.argtypes=args;f.restype=result;return f
create_job=api('CreateJobObjectW',[C.c_void_p,W.LPCWSTR],W.HANDLE)
set_job=api('SetInformationJobObject',[W.HANDLE,C.c_int,C.c_void_p,W.DWORD])
query_job=api('QueryInformationJobObject',[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.c_void_p])
assign=api('AssignProcessToJobObject',[W.HANDLE,W.HANDLE])
close=api('CloseHandle',[W.HANDLE])
terminate=api('TerminateJobObject',[W.HANDLE,W.UINT])
terminate_process=api('TerminateProcess',[W.HANDLE,W.UINT])
resume=api('ResumeThread',[W.HANDLE],W.DWORD)
wait=api('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD)
get_exit=api('GetExitCodeProcess',[W.HANDLE,C.POINTER(W.DWORD)])
create=api('CreateProcessW',[W.LPCWSTR,W.LPWSTR,C.c_void_p,C.c_void_p,W.BOOL,W.DWORD,C.c_void_p,W.LPCWSTR,C.POINTER(Startup),C.POINTER(ProcessInfo)])
def check(v, name):
    if not v: raise C.WinError(C.get_last_error(), name)

def run(command, log, env, timeout, cwd):
    job=create_job(None,None);check(job,'CreateJobObjectW')
    pi=ProcessInfo();started=time.monotonic();timed_out=False
    try:
        limit=Extended();limit.basic.flags=0x2000
        check(set_job(job,9,C.byref(limit),C.sizeof(limit)),'SetInformationJobObject')
        with open(log,'wb') as output, open(os.devnull,'rb') as null:
            hout=msvcrt.get_osfhandle(output.fileno());hin=msvcrt.get_osfhandle(null.fileno())
            os.set_handle_inheritable(hout,True);os.set_handle_inheritable(hin,True)
            si=Startup();si.cb=C.sizeof(si);si.flags=0x100;si.stdin=hin;si.stdout=hout;si.stderr=hout
            line=C.create_unicode_buffer(subprocess.list2cmdline([str(x) for x in command]))
            block=C.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(env.items()))+'\0\0')
            check(create(str(command[0]),line,None,None,True,0x08000404,block,str(cwd),C.byref(si),C.byref(pi)),'CreateProcessW')
            try: check(assign(job,pi.process),'AssignProcessToJobObject')
            except BaseException:
                terminate_process(pi.process,125);raise
            if resume(pi.thread)==0xffffffff:raise C.WinError(C.get_last_error())
            while True:
                state=wait(pi.process,100)
                if state==0:break
                if state!=0x102:raise C.WinError(C.get_last_error())
                if time.monotonic()-started>timeout:
                    check(terminate(job,124),'TerminateJobObject');timed_out=True;break
            wait(pi.process,10000)
            status=W.DWORD();check(get_exit(pi.process,C.byref(status)),'GetExitCodeProcess')
            account=Account();deadline=time.monotonic()+10
            while True:
                check(query_job(job,1,C.byref(account),C.sizeof(account),None),'QueryInformationJobObject')
                if not account.active:break
                if time.monotonic()>deadline:
                    check(terminate(job,125),'TerminateJobObject')
                    wait(pi.process,10000)
                    raise RuntimeError('EQY process exited but descendants remained; terminated whole job')
                time.sleep(.05)
            return dict(exit_code=int(status.value),timed_out=timed_out,
                        elapsed_seconds=time.monotonic()-started,descendant_cleanup_verified=account.active==0,
                        total_job_processes=int(account.total))
    finally:
        if pi.thread:close(pi.thread)
        if pi.process:close(pi.process)
        close(job)
