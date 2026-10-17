"""End-to-end browser acceptance against npm run dev (no mocked API)."""
import json, sys, time, os, shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.media import validate_export

def main():
    evidence=ROOT/'evidence';errors=[];checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':1512,'height':1100},accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:5173');page.wait_for_selector('.scene-editor')
        assert page.locator('.card').count()==8
        page.screenshot(path=str(evidence/'desktop.png'),full_page=True);checks.append('8 template cards and sample scene timeline')
        page.locator('#previewBtn').click()
        page.wait_for_function("document.querySelector('#jobs').textContent.includes('동기화 통과')",timeout=180000)
        page.wait_for_function("document.querySelector('#player').readyState>=2",timeout=30000)
        assert page.locator('#previewState').inner_text()=='현재 편집과 일치 · 검증 완료'
        checks.append('no-upload sample animation renders and plays')
        page.locator('#files').set_input_files([str(evidence/'renders/source-0.mp4'),str(evidence/'renders/source-1.mov')])
        page.wait_for_function("document.querySelectorAll('.file-row').length===2 && [...document.querySelectorAll('.file-row')].every(e=>e.textContent.includes('프록시 준비 완료'))",timeout=90000)
        page.wait_for_function("[...document.querySelectorAll('[data-field=clip_id]')].every(e=>e.value!=='sample')",timeout=30000)
        checks.append('MP4 and MOV upload, proxy, quality analysis')
        page.locator('[data-move="1,-1"]').click();page.wait_for_timeout(400)
        assert 'source-1.mov' in page.locator('.file-title').first.inner_text()
        checks.append('source order changes and composition replans')
        page.locator('#brand').fill('나의 테스트 브랜드')
        page.locator('#hook').fill('일상에서 직접 확인한 제품의 모습을 소개합니다. 긴 한국어 문구도 함께 확인합니다.')
        page.locator('#cta').fill('자세한 정보 확인하기')
        for i in range(6):
            while float(page.locator('.scene-editor').nth(i).locator('.scene-time span').inner_text().replace('초',''))>.5:
                page.locator('.scene-editor').nth(i).locator('[data-duration="-0.5"]').click()
        page.locator('#words').fill('0.10 | 0.70 | 안녕하세요\n0.75 | 1.50 | 한국어\n1.55 | 2.50 | 자막입니다')
        page.locator('#platform').select_option('tiktok')
        page.locator('#musicSelect').select_option('demo')
        page.locator('summary').click();page.locator('#disclosure').fill('유료 광고를 포함합니다')
        page.locator('#insert_disclosure').check();page.locator('#disclosure_confirmed').check()
        page.locator('#presetName').fill('브라우저 검증 스타일');page.locator('#savePreset').click()
        page.wait_for_function("document.querySelector('#presets').options.length===2")
        checks.append('scene duration, Korean copy, subtitles, disclosure, preset save')
        page.locator('#previewBtn').click()
        page.wait_for_function("document.querySelectorAll('.job a[download]').length>=2",timeout=180000)
        page.wait_for_timeout(1800)
        page.locator('#renderBtn').click()
        page.wait_for_function("document.querySelector('#jobs').textContent.includes('1080×1920')",timeout=180000)
        first=page.locator('.job').filter(has_text='1080×1920').first
        with page.expect_download() as download:first.locator('a[download]').click()
        path=evidence/'browser-export.mp4';download.value.save_as(str(path))
        validation=validate_export(path,1080,1920,3)
        checks.append('1080×1920 final render, download and ffprobe validation')
        response=page.request.get('http://127.0.0.1:5173/api/jobs');jobs=response.json()
        preview=next(j for j in jobs if j['kind']=='preview' and j['result'] and j['result']['duration']==3)
        final=next(j for j in jobs if j['kind']=='render' and j['status']=='done')
        assert preview['result']['plan']['scenes']==final['result']['plan']['scenes']
        assert preview['result']['plan']['spec']==final['result']['plan']['spec']
        checks.append('preview/export timing, copy and color plans exactly match')
        page.evaluate("window.scrollTo(0,0);document.querySelector('.preview-pane').scrollTop=0;document.querySelector('#player').pause();document.querySelector('#player').currentTime=1.25;document.querySelector('#scenes').scrollTop=0")
        page.wait_for_timeout(500)
        page.screenshot(path=str(evidence/'editor-result.png'),full_page=True)
        page.reload();page.wait_for_selector('.scene-editor')
        assert page.locator('#brand').input_value()=='나의 테스트 브랜드'
        assert page.locator('#words').input_value().startswith('0.1 |')
        assert page.locator('.job a[download]').count()>=3
        checks.append('draft and job history recover after reload')
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(evidence/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        checks.append('390px mobile layout without horizontal overflow')
        assert not errors,errors
        context.close();browser.close()
    (evidence/'browser-report.json').write_text(json.dumps({'checks':checks,'browser_errors':errors,'download':validation},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':checks,'browser_errors':errors},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
