from playwright.sync_api import sync_playwright
import json, time

captured = []

def record(req_or_resp, kind):
    url = req_or_resp.url if hasattr(req_or_resp, 'url') else '?'
    captured.append({'kind': kind, 'url': url})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    api_requests = []

    def on_request(request):
        if 'consultasimit' in request.url:
            info = {
                'url': request.url,
                'method': request.method,
                'headers': dict(request.headers),
                'body': request.post_data
            }
            api_requests.append(info)
            print(f'>>> REQUEST: {request.method} {request.url[:80]}')
            print(f'    Body: {str(request.post_data)[:300]}')

    def on_response(response):
        if 'consultasimit' in response.url:
            print(f'<<< RESPONSE: {response.status} {response.url[:80]}')
            try:
                body = response.body()
                print(f'    Body: {body[:500].decode("utf-8", errors="replace")}')
            except:
                pass

    page.on('request', on_request)
    page.on('response', on_response)

    # Navigate to the estado-cuenta page
    print('Navigating to SIMIT estado-cuenta...')
    page.goto('https://www.fcm.org.co/simit/', timeout=30000)
    time.sleep(2)

    # Navigate to the hash route
    page.goto('https://www.fcm.org.co/simit/#/estado-cuenta', timeout=30000)
    time.sleep(3)

    print('Current URL:', page.url)

    # Wait for the search input
    try:
        page.wait_for_selector('#txtBusqueda', timeout=15000)
        print('Search input found!')

        # Fill the plate
        page.fill('#txtBusqueda', 'RRC10H')

        # Wait for weHateCaptcha to solve (it runs in background)
        print('Waiting 15s for weHateCaptcha to solve...')
        time.sleep(15)

        # Check if whcQuestions has data
        whc = page.evaluate("sessionStorage.getItem('whcQuestions')")
        print(f'whcQuestions: {whc}')

        # Try clicking the search button
        print('Trying to click search button...')
        for selector in ['#btnNumDocPlaca', 'button[id*="consultar"]', 'button[type="submit"]', '.btn-primary']:
            try:
                element = page.query_selector(selector)
                if element:
                    print(f'Found button: {selector}')
                    element.click()
                    print('Clicked!')
                    break
            except Exception as e:
                print(f'  {selector}: {e}')

        # Also try pressing Enter
        page.fill('#txtBusqueda', 'RRC10H')
        page.press('#txtBusqueda', 'Enter')

        print('Waiting for API response...')
        time.sleep(10)

    except Exception as e:
        print(f'Error: {e}')
        # Print page content for debugging
        print('Page URL:', page.url)
        print('Page title:', page.title())

    browser.close()

print(f'\n=== Captured {len(api_requests)} consultasimit API requests ===')
for req in api_requests:
    print(json.dumps(req, indent=2, ensure_ascii=False))
