import json

src = r"C:\Users\jsgut\Downloads\Speedy Bot — WhatsApp RUNT+SIMIT (4).json"
dst = r"C:\Users\jsgut\OneDrive\Escritorio\CarPlus\CarPlus_Bot_WhatsApp_v5.json"

with open(src, encoding='utf-8') as f:
    data = json.load(f)

NEW_JSCODE = (
    "const staticData = $getWorkflowStaticData('global');\n"
    "if (!staticData.convs) staticData.convs = {};\n"
    "\n"
    "const trigger = $input.first().json;\n"
    "if (!trigger.messages || !trigger.messages[0] || trigger.messages[0].type !== 'text') return [];\n"
    "\n"
    "const phone     = trigger.messages[0].from;\n"
    "const message   = (trigger.messages[0].text?.body || '').trim();\n"
    "const name      = trigger.contacts?.[0]?.profile?.name || phone;\n"
    "const timestamp = new Date().toISOString();\n"
    "const conv      = staticData.convs[phone] || { state: 'WAITING_CEDULA', cedula: '', placa: '', history: [] };\n"
    "\n"
    "const historyLines = (conv.history || []).slice(-6).map(h =>\n"
    "  'Usuario: ' + h.user + '\\nSpeedy Bot: ' + h.bot\n"
    ").join('\\n\\n');\n"
    "\n"
    "let stateInstructions;\n"
    "if (conv.state === 'WAITING_CEDULA') {\n"
    "  stateInstructions =\n"
    "    'INSTRUCCION (WAITING_CEDULA):\\n' +\n"
    "    '- Aun no tienes cedula. Si el mensaje es SOLO digitos (6-12), ES LA CEDULA. Confirmala: \"*Perfecto, cedula NUMERO. Ahora la placa?*\" y pon cedula=NUMERO en el JSON.\\n' +\n"
    "    '- Si el mensaje es un saludo Y el historial esta VACIO, presentate:\\n' +\n"
    "    '  \"Hola! Soy Speedy Bot, tu asistente de documentacion. Para consultar RUNT+SIMIT necesito tu *cedula* y la *placa* de tu vehiculo. Cual es tu *cedula*?\"\\n' +\n"
    "    '- Si el mensaje es un saludo pero YA HAY HISTORIAL, NO te presentes. Solo pide la cedula brevemente.\\n' +\n"
    "    '- Si detectas cedula Y placa en el mismo mensaje, captura ambas y usa action=CONSULT.\\n';\n"
    "} else if (conv.state === 'WAITING_PLACA') {\n"
    "  stateInstructions =\n"
    "    'INSTRUCCION (WAITING_PLACA):\\n' +\n"
    "    '- Ya tienes cedula: ' + conv.cedula + '. Solo falta la placa.\\n' +\n"
    "    '- Si el mensaje tiene formato de placa colombiana (3 letras + 3 chars: ABC123, RRC10H), ES LA PLACA. Confirmala y usa action=CONSULT.\\n' +\n"
    "    '- Si no parece una placa, pide la placa amablemente.\\n' +\n"
    "    '- NUNCA te presentes ni pidas cedula de nuevo.\\n';\n"
    "} else if (conv.state === 'CONSULTING') {\n"
    "  stateInstructions =\n"
    "    'INSTRUCCION (CONSULTING):\\n' +\n"
    "    '- Cedula (' + conv.cedula + ') y placa (' + conv.placa + ') ya capturadas, consulta en proceso.\\n' +\n"
    "    '- Responde: \"Tu consulta esta siendo procesada, en un momento tendras el resultado.\"\\n' +\n"
    "    '- NO pidas cedula ni placa. NO te presentes.\\n';\n"
    "} else {\n"
    "  stateInstructions = 'INSTRUCCION:\\n- Responde el mensaje amablemente.\\n';\n"
    "}\n"
    "\n"
    "const promptCompleto =\n"
    "  'Eres Speedy Bot, asistente de documentacion vehicular para conductores colombianos.\\n' +\n"
    "  'Mision: recolectar CEDULA y PLACA para consultar RUNT+SIMIT.\\n\\n' +\n"
    "  '=== ESTADO ===\\n' +\n"
    "  'ESTADO: ' + conv.state + '\\n' +\n"
    "  'CEDULA: ' + (conv.cedula || 'pendiente') + '\\n' +\n"
    "  'PLACA:  ' + (conv.placa  || 'pendiente') + '\\n\\n' +\n"
    "  '=== HISTORIAL ===\\n' + (historyLines || '(inicio de conversacion)') + '\\n\\n' +\n"
    "  '=== MENSAJE ===\\n\"' + message + '\"\\n\\n' +\n"
    "  '=== ' + stateInstructions + '\\n' +\n"
    "  'REGLAS GENERALES:\\n' +\n"
    "  '- 6-12 digitos solos = cedula colombiana\\n' +\n"
    "  '- 3 letras + 3 chars (letras o digitos) = placa colombiana (RRC10H, ABC123)\\n' +\n"
    "  '- action=CONSULT solo con AMBOS datos validos\\n' +\n"
    "  '- Si menciona no poder renovar por dinero: \"Entiendo. Sin embargo un documento vencido genera bloqueo automatico de tu vinculacion. Contacta al area administrativa.\"\\n' +\n"
    "  '- Usa *negritas* para cedula y placa\\n\\n' +\n"
    "  'RESPONDE UNICAMENTE EN JSON SIN MARKDOWN:\\n' +\n"
    "  '{\"respuesta\":\"texto para WhatsApp\",\"cedula\":\"numero o null\",\"placa\":\"PLACA o null\",\"action\":\"RESPOND o CONSULT\"}';\n"
    "\n"
    "return [{ json: { phone, name, message, timestamp, state: conv.state, cedula: conv.cedula || '', placa: conv.placa || '', history: conv.history || [], promptCompleto } }];"
)

updated = 0
for node in data['nodes']:
    if node.get('name') == 'Preparar Contexto2' and node.get('id') == 'c1b881c5-7d20-48d2-b4fc-aced0d348423':
        node['parameters']['jsCode'] = NEW_JSCODE
        updated += 1
        print(f"Updated: {node['name']}")

print(f"Nodes updated: {updated}")

with open(dst, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"Saved to: {dst}")
