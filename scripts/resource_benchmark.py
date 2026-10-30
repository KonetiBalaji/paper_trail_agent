"""Controlled workload budgets, measured in fresh processes; never calls a model."""
import argparse
import ctypes
import io
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

CASES=('loan_500_rows_50_pages','bank_999_transactions','bank_1000_review','pages_51_rejected','bytes_over_10mb_rejected')

def peak_memory():
    if sys.platform=='win32':
        class Counters(ctypes.Structure):
            _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
        kernel.GetCurrentProcess.restype=ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype=ctypes.c_int
        values=Counters();values.cb=ctypes.sizeof(values)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(values),values.cb):raise OSError('Process memory measurement failed')
        return values.PeakWorkingSetSize,'Windows peak working set'
    import resource
    raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw if sys.platform=='darwin' else raw*1024),'OS peak resident set'

def workload(name):
    if name=='bytes_over_10mb_rejected':return b'%PDF-1.7\n'+b'0'*(10*1024*1024),413,None
    from reportlab.pdfgen import canvas
    output=io.BytesIO();pdf=canvas.Canvas(output,invariant=1)
    if name=='pages_51_rejected':
        for index in range(51):pdf.drawString(40,750,f'Fictional page {index+1}');pdf.showPage()
        expected_http,status=422,None
    elif name=='loan_500_rows_50_pages':
        for page in range(50):
            lines=['Loan: RESOURCE-DEMO','Currency: USD','Period end: 2026-10-31']
            lines += [f'Tranche T{page*10+row} | Principal: 1.00 | Interest: 0.10' for row in range(10)]
            if page==49:lines.append('Stated principal plus interest total: 550.00')
            for index,line in enumerate(lines):pdf.drawString(35,760-index*25,line)
            pdf.showPage()
        expected_http,status=200,'consistent'
    else:
        count=999 if name=='bank_999_transactions' else 1000
        lines=['Account: RESOURCE-DEMO Currency: USD','Statement period end: 2026-10-31','Opening balance: 0.00']
        lines += [f'Transaction T{index} | 2026-10-02 | Amount: 1.00' for index in range(count)]
        lines += [f'Closing balance: {count}.00']
        for index,line in enumerate(lines):
            if index and index%30==0:pdf.showPage()
            pdf.drawString(35,760-(index%30)*22,line)
        expected_http,status=200,'consistent' if count==999 else 'review'
    pdf.save();return output.getvalue(),expected_http,status

def child(name):
    from fastapi import HTTPException,UploadFile
    from app.main import analyze_files
    raw,expected_http,status=workload(name);started=time.perf_counter();observed=200;report=None
    try:report=analyze_files([UploadFile(filename='resource-synthetic.pdf',file=io.BytesIO(raw))],'local',persist=False)
    except HTTPException as exc:observed=exc.status_code
    elapsed=time.perf_counter()-started;peak,method=peak_memory()
    passed=observed==expected_http and (report is None if status is None else report is not None and report['status']==status)
    if name=='loan_500_rows_50_pages':passed=passed and report['calculations'][0]['computed']=='550.00'
    if name=='bank_999_transactions':passed=passed and report['calculations'][0]['computed']=='999.00'
    if name=='bank_1000_review':passed=passed and any(finding['type']=='calculation_limit' for finding in report['findings']) and not report['calculations']
    return {'case':name,'passed':bool(passed),'input_bytes':len(raw),'http_status':observed,
        'status':report['status'] if report else 'rejected','analysis_seconds':round(elapsed,4),
        'peak_process_memory_bytes':peak,'memory_measurement':method,'model_calls':0}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--child',choices=CASES)
    parser.add_argument('--report',type=Path);parser.add_argument('--max-rss-mb',type=int,default=512)
    parser.add_argument('--max-analysis-seconds',type=float,default=20)
    args=parser.parse_args()
    if args.child:print(json.dumps(child(args.child)));return
    rows=[]
    for name in CASES:
        try:
            process=subprocess.run([sys.executable,__file__,'--child',name],text=True,capture_output=True,timeout=45)
            if process.returncode:raise ValueError('Child benchmark failed')
            row=json.loads(process.stdout)
            row['within_budget']=row['peak_process_memory_bytes']<=args.max_rss_mb*1024*1024 and row['analysis_seconds']<=args.max_analysis_seconds
        except (subprocess.TimeoutExpired,ValueError):row={'case':name,'passed':False,'within_budget':False,'error':'Child failed, timed out, or returned invalid metrics'}
        rows.append(row);print(('PASS' if row['passed'] and row['within_budget'] else 'FAIL'),name)
    result={'platform':platform.system(),'python':platform.python_version(),'cases':rows,
        'budget':{'peak_memory_mb':args.max_rss_mb,'analysis_seconds':args.max_analysis_seconds,'child_watchdog_seconds':45},
        'scope':'Controlled fictional workloads in fresh local processes. Budgets are test gates, not a sandbox or production guarantee for arbitrary PDFs.',
        'passed':all(row['passed'] and row['within_budget'] for row in rows)}
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)

if __name__=='__main__':main()
