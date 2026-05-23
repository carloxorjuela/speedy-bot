from playwright.sync_api import sync_playwright
import json, time

captured_requests = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    def on_request(request):
        if 'consultasimit' in request.url or 'estadocuenta' in request.url or 'qxcaptcha' in request.url:
            captured_requests.append({
                'url': request.url,
                'method': request.method,
                'headers': dict(request.headers),
                'body': request.post_data
            })
            print(f'REQUEST: {request.method} {request.url}')
            print(f'Headers: {json.dumps(dict(request.headers), indent=2)}')
            if request.post_data:
                print(f'Body: {request.post_data[:1000]}')
            print()

    def on_response(response):
        if 'consultasimit' in response.url or 'estadocuenta' in response.url:
            try:
                body = response.json()
                print(f'RESPONSE: {response.status} {response.url}')
                print(f'Body: {json.dumps(body, ensure_ascii=False)[:2000]}')
            except:
                print(f'RESPONSE: {response.status} {response.url} (non-JSON)')

    page.on('request', on_request)
    page.on('response', on_response)

    print('Navigating to SIMIT...')
    page.goto('https://www.fcm.org.co/simit/', timeout=30000, wait_until='networkidle')

    print('Looking for form...')
    try:
        page.wait_for_selector('#txtBusqueda', timeout=10000)
        print('Form found! Filling plate...')
        page.fill('#txtBusqueda', 'RRC10H')

        print('Waiting 8s for captcha to auto-solve...')
        time.sleep(8)

        print('Clicking search button...')
        try:
            page.click('#consultar', timeout=3000)
        except:
            page.click('#btnNumDocPlaca', timeout=3000)

        print('Waiting for API response...')
        time.sleep(10)

    except Exception as e:
        print(f'Error: {e}')

    browser.close()

print(f'\n=== Captured {len(captured_requests)} API requests ===')
for req in captured_requests:
    print(json.dumps(req, indent=2, ensure_ascii=False))
