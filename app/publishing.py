"""Opt-in YouTube module. Never called by editor/render/preview jobs.
Install google-api-python-client + google-auth-oauthlib separately.
OAuth desktop client and an explicit --confirm-publish flag are required.
"""
import argparse, json
from pathlib import Path

SCOPES=['https://www.googleapis.com/auth/youtube.upload']
def upload_youtube(video:Path,title:str,description:str,client_secrets:Path,token_file:Path,privacy='private'):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds=Credentials.from_authorized_user_file(str(token_file),SCOPES) if token_file.exists() else None
    if creds and creds.expired and creds.refresh_token:creds.refresh(Request())
    if not creds or not creds.valid:
        creds=InstalledAppFlow.from_client_secrets_file(str(client_secrets),SCOPES).run_local_server(port=0)
    token_file.parent.mkdir(parents=True,exist_ok=True)
    token_file.write_text(creds.to_json());token_file.chmod(0o600)
    youtube=build('youtube','v3',credentials=creds)
    request=youtube.videos().insert(part='snippet,status',body={'snippet':{'title':title,'description':description,'categoryId':'22'},
        'status':{'privacyStatus':privacy,'selfDeclaredMadeForKids':False}},media_body=MediaFileUpload(str(video),mimetype='video/mp4',chunksize=8*1024*1024,resumable=True))
    result=None
    while result is None:_,result=request.next_chunk()
    return {'id':result['id'],'privacy':privacy}

def main():
    p=argparse.ArgumentParser(description='공식 YouTube API / 사용자 OAuth 인증 / 기본 비공개 업로드')
    p.add_argument('video',type=Path);p.add_argument('--title',required=True);p.add_argument('--description',default='')
    p.add_argument('--client-secrets',type=Path,required=True);p.add_argument('--token-file',type=Path,required=True)
    p.add_argument('--privacy',choices=['private','unlisted','public'],default='private');p.add_argument('--confirm-publish',action='store_true')
    a=p.parse_args()
    if not a.confirm_publish:p.error('게시 계정·영상·제목·공개 범위를 확인한 뒤 --confirm-publish를 명시하세요.')
    if not a.video.is_file():p.error('동영상 파일이 없습니다.')
    print(json.dumps(upload_youtube(a.video,a.title,a.description,a.client_secrets,a.token_file,a.privacy)))
if __name__=='__main__':main()
