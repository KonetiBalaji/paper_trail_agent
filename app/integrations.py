"""Server-to-server API. Bearer keys never authorize interactive platform routes."""
from typing import Literal
from fastapi import APIRouter,Depends,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import Response
from .security import Unauthorized
from .privacy import report_for_export
from .exports import csv_report


def create_router(resources,analyze_files,service_mode):
    router=APIRouter(prefix='/api/integrations/v1')
    def access(scope):
        def authenticate(request:Request):
            if not service_mode():raise HTTPException(409,'Integration API requires authenticated database service mode')
            repo,security=resources()
            repo.consume('api-auth:'+security.digest(request.client.host if request.client else 'unknown'),120,60)
            header=request.headers.get('Authorization','')
            try:actor=security.authenticate_api(header[7:] if header.startswith('Bearer ') else '',scope)
            except Unauthorized:raise HTTPException(401,'Invalid API credentials or required scope',headers={'WWW-Authenticate':'Bearer'}) from None
            repo.consume('api-minute:'+actor.key_id,60,60)
            repo.consume('api-day:'+actor.key_id,1000,86400)
            repo.consume('api-workspace-day:'+actor.workspace,5000,86400)
            return actor
        return authenticate

    def submit_files(response, files, mode, actor, origin):
        repo,_=resources();repo.consume('analysis:'+actor.workspace,20,3600)
        from .ingestion import intake
        report=intake(repo,actor.workspace,actor.id,files,mode,origin,analyze_files)
        response.status_code=201 if report['intake_receipt']['created'] else 200
        return {'id':report['id'],'status':report['status'],'report_version':report['report_version'],'mode':report.get('mode','local'),
                'created':report['intake_receipt']['created']}

    @router.post('/cases',status_code=201,responses={200:{'description':'Existing identical analysis reused'}})
    def submit(response:Response,files:list[UploadFile]=File(...),mode:Literal['local']=Form('local'),actor=Depends(access('cases:submit'))):
        return submit_files(response, files, mode, actor, 'api')

    @router.post('/email', status_code=201, responses={200: {'description': 'Existing identical analysis reused'}})
    def submit_email(response: Response, message: UploadFile = File(...), actor=Depends(access('cases:submit'))):
        from .email_intake import pdf_attachments
        return submit_files(response, pdf_attachments(message), 'local', actor, 'email')

    @router.get('/cases/{case_id}')
    def read(case_id,version:int|None=None,actor=Depends(access('cases:read'))):
        return report_for_export(resources()[0].get_case(actor.workspace,case_id,version))

    @router.get('/cases/{case_id}/export')
    def export(case_id,format:Literal['json','csv','accounting_csv']='json',version:int|None=None,actor=Depends(access('cases:read'))):
        report=resources()[0].get_case(actor.workspace,case_id,version)
        if format=='json':return report_for_export(report)
        return Response(csv_report(report,accounting=format=='accounting_csv'),media_type='text/csv',
                        headers={'Content-Disposition':'attachment; filename=paper-trail-'+format+'.csv'})
    return router
