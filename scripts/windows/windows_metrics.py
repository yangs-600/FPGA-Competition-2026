"""Windows process-tree CPU and root-process peak working-set measurement."""
import ctypes as C
from ctypes import wintypes as W
import json, msvcrt, os, subprocess, sys, time
from pathlib import Path

K = C.WinDLL('kernel32', use_last_error=True)
P = C.WinDLL('psapi', use_last_error=True)
SIZE = C.c_size_t

class Startup(C.Structure):
    _fields_ = [('cb',W.DWORD),('reserved',W.LPWSTR),('desktop',W.LPWSTR),('title',W.LPWSTR),
                ('x',W.DWORD),('y',W.DWORD),('xs',W.DWORD),('ys',W.DWORD),
                ('charsx',W.DWORD),('charsy',W.DWORD),('fill',W.DWORD),('flags',W.DWORD),
                ('show',W.WORD),('cbreserved',W.WORD),('lpreserved',C.c_void_p),
                ('stdin',W.HANDLE),('stdout',W.HANDLE),('stderr',W.HANDLE)]
class ProcessInfo(C.Structure):
    _fields_ = [('process',W.HANDLE),('thread',W.HANDLE),('pid',W.DWORD),('tid',W.DWORD)]
class Account(C.Structure):
    _fields_ = [(n,C.c_longlong) for n in ('user','kernel','perioduser','periodkernel')] + [
                (n,W.DWORD) for n in ('faults','total','active','terminated')]
class BasicLimit(C.Structure):
    _fields_ = [('process_time',C.c_longlong),('job_time',C.c_longlong),('flags',W.DWORD),
                ('min_ws',SIZE),('max_ws',SIZE),('active',W.DWORD),('affinity',SIZE),
                ('priority',W.DWORD),('scheduling',W.DWORD)]
class IOCounters(C.Structure):
    _fields_ = [(n,C.c_ulonglong) for n in ('read','write','other','readbytes','writebytes','otherbytes')]
class ExtendedLimit(C.Structure):
    _fields_ = [('basic',BasicLimit),('io',IOCounters),('process_memory',SIZE),
                ('job_memory',SIZE),('peak_process_memory',SIZE),('peak_job_memory',SIZE)]
class Memory(C.Structure):
    _fields_ = [('cb',W.DWORD),('faults',W.DWORD)] + [(n,SIZE) for n in (
                'peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]

def api(dll, name, argtypes, restype=W.BOOL):
    f=getattr(dll,name); f.argtypes=argtypes; f.restype=restype; return f
create_job=api(K,'CreateJobObjectW',[C.c_void_p,W.LPCWSTR],W.HANDLE)
set_job=api(K,'SetInformationJobObject',[W.HANDLE,C.c_int,C.c_void_p,W.DWORD])
query_job=api(K,'QueryInformationJobObject',[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.c_void_p])
assign=api(K,'AssignProcessToJobObject',[W.HANDLE,W.HANDLE])
close=api(K,'CloseHandle',[W.HANDLE])
terminate=api(K,'TerminateJobObject',[W.HANDLE,W.UINT])
terminate_process=api(K,'TerminateProcess',[W.HANDLE,W.UINT])
resume=api(K,'ResumeThread',[W.HANDLE],W.DWORD)
wait=api(K,'WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD)
exit_code=api(K,'GetExitCodeProcess',[W.HANDLE,C.POINTER(W.DWORD)])
process_times=api(K,'GetProcessTimes',[W.HANDLE]+[C.POINTER(W.FILETIME)]*4)
memory_info=api(P,'GetProcessMemoryInfo',[W.HANDLE,C.POINTER(Memory),W.DWORD])
create_process=api(K,'CreateProcessW',[W.LPCWSTR,W.LPWSTR,C.c_void_p,C.c_void_p,W.BOOL,
                    W.DWORD,C.c_void_p,W.LPCWSTR,C.POINTER(Startup),C.POINTER(ProcessInfo)])

def check(result, name):
    if not result: raise C.WinError(C.get_last_error(), name)
def filetime(t):
    return ((t.dwHighDateTime<<32)|t.dwLowDateTime)/1e7

def measure(command, logfile, env=None, cwd=None, timeout=120):
    job=create_job(None,None); check(job,'CreateJobObjectW')
    pi=ProcessInfo(); peak=0; samples=0; final_memory_ok=False
    try:
        limit=ExtendedLimit(); limit.basic.flags=0x2000 # KILL_ON_JOB_CLOSE
        check(set_job(job,9,C.byref(limit),C.sizeof(limit)),'SetInformationJobObject')
        with open(logfile,'wb') as log, open(os.devnull,'rb') as null:
            hout=msvcrt.get_osfhandle(log.fileno()); hin=msvcrt.get_osfhandle(null.fileno())
            os.set_handle_inheritable(hout,True); os.set_handle_inheritable(hin,True)
            startup=Startup();startup.cb=C.sizeof(startup);startup.flags=0x100
            startup.stdin=hin;startup.stdout=hout;startup.stderr=hout
            commandline=C.create_unicode_buffer(subprocess.list2cmdline([str(c) for c in command]))
            block=C.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted((env or os.environ).items()))+'\0\0')
            start=time.perf_counter()
            check(create_process(str(command[0]),commandline,None,None,True,0x08000404,
                  block,str(cwd) if cwd else None,C.byref(startup),C.byref(pi)),'CreateProcessW')
            try: check(assign(job,pi.process),'AssignProcessToJobObject')
            except BaseException:
                terminate_process(pi.process,1);raise
            if resume(pi.thread)==0xffffffff: raise C.WinError(C.get_last_error(),'ResumeThread')
            while True:
                mem=Memory();mem.cb=C.sizeof(mem)
                if memory_info(pi.process,C.byref(mem),C.sizeof(mem)):
                    peak=max(peak,mem.peak_ws);samples+=1
                state=wait(pi.process,2)
                if state==0:break
                if state!=0x102:raise C.WinError(C.get_last_error(),'WaitForSingleObject')
                if time.perf_counter()-start>timeout:
                    terminate(job,1);raise TimeoutError('Whole synthesis exceeded timeout')
            wall=time.perf_counter()-start
            mem=Memory();mem.cb=C.sizeof(mem)
            if memory_info(pi.process,C.byref(mem),C.sizeof(mem)):
                peak=max(peak,mem.peak_ws);samples+=1;final_memory_ok=True
            status=W.DWORD();check(exit_code(pi.process,C.byref(status)),'GetExitCodeProcess')
            created,exited,kernel,user=(W.FILETIME() for _ in range(4))
            check(process_times(pi.process,*[C.byref(t) for t in (created,exited,kernel,user)]),'GetProcessTimes')
            account=Account();check(query_job(job,1,C.byref(account),C.sizeof(account),None),'QueryInformationJobObject')
            # Yosys must wait for ABC. A live descendant at root exit is an invalid measurement.
            deadline=time.perf_counter()+5
            while account.active:
                if time.perf_counter()>deadline:raise RuntimeError('Descendants survived root process')
                time.sleep(.002)
                check(query_job(job,1,C.byref(account),C.sizeof(account),None),'QueryInformationJobObject')
            if not peak or not samples or not final_memory_ok:
                raise RuntimeError('Complete root-process peak working-set counters unavailable')
            result=dict(exit_code=status.value,cpu_seconds=(account.user+account.kernel)/1e7,
                        root_cpu_seconds=filetime(user)+filetime(kernel),wall_seconds=wall,
                        peak_working_set_bytes=peak,total_job_processes=account.total,
                        active_job_processes=account.active,limit_terminated_processes=account.terminated,
                        memory_counter_reads=samples,final_memory_counter_read=final_memory_ok)
            if status.value:raise RuntimeError('Process failed: '+str(logfile)+' '+str(result))
            return result
    finally:
        if pi.thread:close(pi.thread)
        if pi.process:close(pi.process)
        close(job)

def self_test(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    child="import time; b=bytearray(128*2**20); s=time.process_time();\nwhile time.process_time()-s<0.5: pass"
    parent="import subprocess,sys,time; b=bytearray(64*2**20); subprocess.run([sys.executable,'-c',"+repr(child)+"],check=True); time.sleep(.04)"
    r=measure([sys.executable,'-c',parent],out/'meter-positive-control.log')
    if not (r['total_job_processes']>=2 and r['cpu_seconds']-r['root_cpu_seconds']>=.45 and
            64*2**20<=r['peak_working_set_bytes']<128*2**20 and r['final_memory_counter_read']):
        raise RuntimeError('CPU inclusion/root-memory positive control failed: '+repr(r))
    (out/'meter-positive-control.json').write_text(json.dumps(r,indent=2),encoding='utf8')
    print(json.dumps(r,indent=2))

if __name__=='__main__':
    self_test(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'meter-test')
