"""Real Chromium-to-FastAPI browser smoke; deterministic synthetic cases only.

Run `python scripts/browser_smoke.py` after installing requirements-browser.txt.
No external network, live PII or lender credentials are used.
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory(prefix='aadharshila-browser-') as scratch:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'APP_ENV':'development','SEED_DEMO':'true',
             'DATABASE_URL':'sqlite:///'+str(Path(scratch)/'e2e.sqlite'),
             'UPLOAD_DIR':str(Path(scratch)/'documents'),
             'PYTHONPATH':str(ROOT/'src')}
        api=subprocess.Popen([sys.executable,'-m','uvicorn','aadharshila.main:app',
                         '--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,
                         stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base+'/health/ready',timeout=1) as response:
                        if response.status==200:break
                except Exception:time.sleep(.1)
            else:raise AssertionError('FastAPI did not become ready')
            with sync_playwright() as playwright:
                browser_args={'headless':True}
                if os.getenv('CHROMIUM_PATH'):browser_args['executable_path']=os.environ['CHROMIUM_PATH']
                browser=playwright.chromium.launch(**browser_args)
                try:
                    page=browser.new_page()
                    errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(base+'/',wait_until='networkidle',timeout=15000)
                    page.locator('#username').select_option('analyst')
                    page.locator('#password').fill('Demo@12345')
                    page.locator('#login-form button[type=submit]').click()
                    page.locator('#shell:not(.hidden)').wait_for(timeout=10000)
                    page.get_by_role('heading',name='Underwriting overview').wait_for(state='visible',timeout=15000)
                    page.get_by_role('button',name='Application queue').first.click()
                    page.get_by_text('AS-1001').first.wait_for(timeout=8000)
                    page.get_by_role('button',name='Decision explanation').first.click()
                    page.get_by_role('heading',name='Decision explanation').wait_for(state='visible',timeout=15000)
                    page.get_by_role('button',name='Document vault').first.click()
                    page.get_by_role('heading',name='Document vault').wait_for(state='visible',timeout=15000)
                    page.get_by_text('Stored documents').first.wait_for(timeout=8000)
                    # Advisory ML evidence review: real browser + FastAPI + synthetic fixture.
                    page.get_by_role('button',name='Evidence intelligence · ML').first.click()
                    page.get_by_role('heading',name='Evidence intelligence').wait_for(state='visible',timeout=15000)
                    page.locator('#case-choose').select_option(label='AS-1004 · Arjun Verma')
                    page.locator('#intelligence-input').wait_for(state='visible',timeout=8000)
                    page.wait_for_function("() => document.querySelector('#intelligence-input')?.value.includes('820000')",timeout=12000)
                    page.get_by_role('button',name='Run evidence analysis').click()
                    page.get_by_text('UNSUPERVISED ML',exact=False).first.wait_for(state='visible',timeout=15000)
                    page.get_by_text('INCOME CONTRADICTION',exact=False).first.wait_for(state='visible',timeout=15000)
                    assert '820000' in page.locator('#intelligence-input').input_value()
                    assert not errors,'Browser JS failures: '+str(errors)
                    page.locator('#logout').click()
                    page.locator('#login:not(.hidden)').wait_for(timeout=8000)
                    return {'status':'PASS','real_browser':True,
                            'scenarios':['login','overview','queue','decision','documents','advisory-ml-review','logout'],
                            'javascript_errors':0}
                finally:browser.close()
        finally:
            api.terminate()
            try:api.communicate(timeout=5)
            except subprocess.TimeoutExpired:api.kill();api.communicate()

if __name__=='__main__':
    print(run())
