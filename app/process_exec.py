"""Linux subprocess wrapper: reap FFmpeg if its owning worker is killed."""
import ctypes
import os
import signal
import sys
parent=os.getppid()
libc=ctypes.CDLL(None,use_errno=True)
if libc.prctl(1,signal.SIGTERM,0,0,0)!=0:
    raise OSError(ctypes.get_errno(),'PR_SET_PDEATHSIG failed')
if os.getppid()!=parent or parent==1:raise SystemExit(1)
os.execvp(sys.argv[1],sys.argv[1:])
