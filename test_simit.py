import requests, json, hashlib, time, math

def is_prime(n):
    if n < 2: return False
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0: return False
    return True

def solve_captcha(question, timestamp):
    nonce = 1
    while True:
        nonce += 1
        verify_array = {'question': question, 'time': timestamp, 'nonce': nonce}
        verify_json = json.dumps(verify_array, separators=(',', ':'))
        current_hash = hashlib.sha256(verify_json.encode()).hexdigest()
        if current_hash.startswith('0000') and is_prime(nonce):
            return verify_array

# Get question
r = requests.post('https://qxcaptcha.fcm.org.co/api.php', data={'endpoint': 'question'}, timeout=10)
print(f'qxcaptcha response: {r.status_code} {r.text[:200]}')
question = r.json()['data']['question']
timestamp = int(time.time())
verify_array = solve_captcha(question, timestamp)
captcha_response = json.dumps([verify_array])
print(f'Solved PoW: nonce={verify_array["nonce"]}')

# Replicate exactly the browser request (no Origin, sec-ch-ua headers, consumidor as string)
payload = json.dumps({
    'filtro': 'RRC10H',
    'reCaptchaDTO': {
        'response': captcha_response,
        'consumidor': '1'  # STRING, not int!
    }
})

headers = {
    'sec-ch-ua-platform': '"Windows"',
    'referer': 'https://www.fcm.org.co/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'accept': '*/*',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'content-type': 'application/json',
    'sec-ch-ua-mobile': '?0',
    # NO Origin header!
}

r2 = requests.post(
    'https://consultasimit.fcm.org.co/simit/microservices/estado-cuenta-simit/estadocuenta/consulta',
    data=payload,
    headers=headers,
    timeout=20
)
print(f'Status: {r2.status_code}')
print(f'Response: {r2.text[:3000]}')
