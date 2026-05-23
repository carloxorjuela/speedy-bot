"""Test SIMIT scraper using Playwright to bypass WAF and auto-solve weHateCaptcha."""
from playwright.sync_api import sync_playwright
import json, time

def consultar_simit(placa: str, timeout_captcha: int = 30) -> dict:
    """Query SIMIT estadocuenta for a plate. Returns parsed JSON response."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        resultado = {}

        def on_response(response):
            if 'estadocuenta/consulta' in response.url:
                try:
                    body = response.json()
                    resultado.update({'data': body, 'status': response.status})
                except Exception as e:
                    resultado.update({'error': str(e), 'status': response.status})

        page.on('response', on_response)

        # Navigate to SIMIT (triggers weHateCaptcha auto-solve in background)
        page.goto('https://www.fcm.org.co/simit/#/estado-cuenta', timeout=30000, wait_until='domcontentloaded')
        time.sleep(2)

        # Wait for weHateCaptcha to solve (difficulty=1, usually takes 3-10s)
        start = time.time()
        while time.time() - start < timeout_captcha:
            whc_raw = page.evaluate("sessionStorage.getItem('whcQuestions')")
            if whc_raw:
                whc = json.loads(whc_raw)
                if whc.get('questions') and len(whc['questions']) > 0:
                    break
            time.sleep(1)
        else:
            browser.close()
            return {'error': 'weHateCaptcha timeout'}

        # Let JS call the API directly by filling the form and submitting
        page.wait_for_selector('#txtBusqueda', timeout=10000)
        page.fill('#txtBusqueda', placa)

        # Dismiss any modal overlay first
        page.evaluate("""
            var modal = document.getElementById('modalInformation');
            if (modal) {
                modal.classList.remove('show');
                modal.style.display = 'none';
            }
            document.querySelectorAll('.modal-backdrop').forEach(e => e.remove());
            document.body.classList.remove('modal-open');
        """)

        # Use jQuery AJAX directly (same as the site uses)
        captcha_response = page.evaluate("""
            var whc = JSON.parse(sessionStorage.getItem('whcQuestions'));
            var token = whc.questions.pop();
            sessionStorage.setItem('whcQuestions', JSON.stringify(whc));
            JSON.stringify(token);
        """)

        print(f'Using captcha token: {captcha_response}')

        # Make the API call via fetch from the browser context
        result = page.evaluate(f"""
            async () => {{
                const payload = {{
                    filtro: '{placa}',
                    reCaptchaDTO: {{
                        response: {json.dumps(captcha_response)},
                        consumidor: '1'
                    }}
                }};
                const response = await fetch(
                    'https://consultasimit.fcm.org.co/simit/microservices/estado-cuenta-simit/estadocuenta/consulta',
                    {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                            'Accept': '*/*',
                        }},
                        body: JSON.stringify(payload)
                    }}
                );
                const text = await response.text();
                return {{ status: response.status, body: text }};
            }}
        """)

        browser.close()
        print(f'API Status: {result["status"]}')
        print(f'API Response: {result["body"][:3000]}')
        return result

if __name__ == '__main__':
    result = consultar_simit('RRC10H')
