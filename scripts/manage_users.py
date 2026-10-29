"""Provision a service account interactively; passwords never appear in argv."""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env')
from app.platform import runtime

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email',required=True)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--role',choices=['admin','reviewer','viewer'],default='reviewer')
    args=parser.parse_args()
    password=getpass.getpass('New account password (12+ characters): ')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ; nothing changed.')
    root=Path(__file__).resolve().parents[1]/'storage'
    repo,security=runtime(root)
    result=security.create_user(args.email,password,args.workspace,args.role)
    print('Account provisioned:',result['id'],'role:',result['role'])

if __name__=='__main__':main()
