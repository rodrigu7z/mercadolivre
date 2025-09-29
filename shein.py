from flask import Flask, request, send_file, jsonify, render_template, after_this_request
import fitz
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.graphics.barcode import code128
from reportlab.lib.utils import ImageReader
import io
from PIL import Image
import re
import time
import os
import traceback
import atexit
import tempfile
from flask_cors import CORS

HTML_TEMPLATE = """

"""

app = Flask(__name__)
CORS(app)  # Adiciona suporte CORS para permitir requisições de diferentes origens

# Configurar limite de tamanho de upload para 50MB
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB em bytes

# Lista para rastrear arquivos temporários
temp_files = []  

# Função para limpar arquivos temporários
def cleanup_temp_files():
    for file_path in temp_files:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Arquivo temporário removido: {file_path}")
        except Exception as e:
            print(f"Erro ao remover arquivo temporário {file_path}: {str(e)}")
    temp_files.clear()

# Registrar função de limpeza para ser executada quando o aplicativo for encerrado
atexit.register(cleanup_temp_files)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/processar-pdf', methods=['POST'])
@app.route('/api/processar-pdf', methods=['POST'])
def processar_pdf():
    # Criar arquivos temporários com o módulo tempfile para garantir limpeza adequada
    input_pdf_fd, input_pdf = tempfile.mkstemp(suffix='.pdf', prefix='temp_input_')
    output_pdf_fd, output_pdf = tempfile.mkstemp(suffix='.pdf', prefix='temp_output_')
    
    # Fechar os descritores de arquivo criados pelo tempfile
    os.close(input_pdf_fd)
    os.close(output_pdf_fd)
    
    # Adicionar à lista de arquivos temporários para garantir limpeza
    temp_files.append(input_pdf)
    temp_files.append(output_pdf)
    
    try:
        # Verifica se foi enviado um arquivo
        if 'arquivo' not in request.files:
            return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
            
        arquivo = request.files['arquivo']
        
        # Verifica se o nome do arquivo está vazio
        if arquivo.filename == '':
            return jsonify({'erro': 'Nome do arquivo vazio'}), 400
        
        # Salva o arquivo temporariamente
        arquivo.save(input_pdf)
        
        # Processa o PDF
        extracted_data = extract_text_from_pdf(input_pdf)
        if extracted_data:
            create_individual_page_pdf(output_pdf, extracted_data, input_pdf)
            
            # Registra função para limpar os arquivos após o request
            @after_this_request
            def cleanup_after_request(response):
                try:
                    # Remover os arquivos temporários após o envio da resposta
                    if os.path.exists(input_pdf):
                        os.remove(input_pdf)
                        temp_files.remove(input_pdf)
                        print(f"Arquivo temporário removido após request: {input_pdf}")
                    if os.path.exists(output_pdf):
                        os.remove(output_pdf)
                        temp_files.remove(output_pdf)
                        print(f"Arquivo temporário removido após request: {output_pdf}")
                except Exception as e:
                    print(f"Erro ao remover arquivos temporários após request: {str(e)}")
                return response
            
            # Envia o arquivo processado como resposta
            try:
                response = send_file(
                    output_pdf,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name='processado.pdf'
                )
                
                return response
            except Exception as e:
                # Se houver erro ao enviar o arquivo, tenta remover os temporários
                print(f"Erro ao enviar o arquivo: {str(e)}")
                try:
                    if os.path.exists(input_pdf):
                        os.remove(input_pdf)
                        temp_files.remove(input_pdf)
                    if os.path.exists(output_pdf):
                        os.remove(output_pdf)
                        temp_files.remove(output_pdf)
                except Exception as cleanup_error:
                    print(f"Erro ao limpar arquivos após falha de envio: {str(cleanup_error)}")
                raise
        else:
            # Se não extraiu dados, remove o arquivo de entrada
            try:
                if os.path.exists(input_pdf):
                    os.remove(input_pdf)
                    temp_files.remove(input_pdf)
                if os.path.exists(output_pdf):
                    os.remove(output_pdf)
                    temp_files.remove(output_pdf)
            except Exception as e:
                print(f"Erro ao remover arquivos temporários: {str(e)}")
                
            return jsonify({
                'erro': 'Nenhum dado extraído do PDF', 
                'mensagem': 'O PDF enviado não parece conter o formato esperado. Certifique-se de que o PDF contém uma DANFE com a chave de acesso e itens.'
            }), 400
            
    except Exception as e:
        # Log do erro completo para debug
        error_trace = traceback.format_exc()
        print(error_trace)
        
        # Limpar arquivos temporários em caso de erro
        try:
            if os.path.exists(input_pdf):
                os.remove(input_pdf)
                temp_files.remove(input_pdf)
            if os.path.exists(output_pdf):
                os.remove(output_pdf)
                temp_files.remove(output_pdf)
        except Exception as cleanup_error:
            print(f"Erro ao limpar arquivos temporários: {str(cleanup_error)}")
        
        # Mensagem de erro mais amigável para o usuário
        error_message = str(e)
        if "already being used by another process" in error_message:
            user_message = "O arquivo está sendo usado por outro processo. Por favor, tente novamente em alguns instantes."
        elif "Permission denied" in error_message:
            user_message = "Erro de permissão ao acessar os arquivos. Por favor, tente novamente."
        else:
            user_message = "Ocorreu um erro ao processar o PDF. Por favor, verifique se o formato está correto e tente novamente."
            
        return jsonify({
            'erro': str(e),
            'mensagem': user_message
        }), 500

# Resto do código permanece igual
def extract_text_from_pdf(input_pdf):
    inicio = time.time()
    doc = fitz.open(input_pdf)
    extracted_data = []
    page_num = 0
    while page_num < doc.page_count:
        page = doc.load_page(page_num)
        text = page.get_text("text")

        if not text.startswith("DANFE"):
            page_num += 1
            continue

        try:
            chave_acesso_index = text.index("CHAVE DE ACESSO")
            chave_acesso = text[chave_acesso_index + len("CHAVE DE ACESSO"):].strip().split('\n')[0]

            item_index = text.index("ITEM")
            texto_completo = text[item_index:]

            proxima_pagina = page_num + 1
            if proxima_pagina < doc.page_count:
                next_page = doc.load_page(proxima_pagina)
                if not next_page.get_images():
                    next_text = next_page.get_text("text")
                    texto_completo += next_text

            linhas = texto_completo.strip().split('\n')
            
            itens = []
            item_atual = []
            
            for linha in linhas[1:]:
                if linha.strip() in ["CONTEÚDO", "ATRIBUTOS", "QUANT."]:
                    continue
                    
                if linha.strip() == "1":
                    if item_atual:
                        codigo = item_atual[0]
                        conteudo = " ".join(item_atual[1:])
                        itens.append([codigo, conteudo, "1"])
                        item_atual = []
                elif linha.strip():
                    item_atual.append(linha.strip())
            
            if item_atual:
                codigo = item_atual[0]
                conteudo = " ".join(item_atual[1:])
                itens.append([codigo, conteudo, "1"])

            extracted_data.append([chave_acesso, itens])

        except ValueError:
            print(f"Erro ao extrair dados na página {page_num + 1}")

        page_num += 2

    doc.close()
    fim = time.time()
    print(f"Tempo de execução da extração: {fim - inicio} segundos")
    return extracted_data

def create_individual_page_pdf(output_pdf, data, input_pdf):
    inicio = time.time()
    doc = fitz.open(input_pdf)
    c = canvas.Canvas(output_pdf, pagesize=(799, 1197))
    width, height = c._pagesize

    for i, row in enumerate(data):
        chave_acesso, itens = row

        barcode = code128.Code128(chave_acesso, barHeight=1.8 * cm, barWidth=0.05 * cm)
        c.saveState()
        c.rotate(90)
        barcode.drawOn(c, height - 14.00 * cm - 0.80 * cm, -width + 0.50 * cm)
        c.restoreState()

        text_x = width - 0.10 * cm
        text_y = height - 12.0 * cm
        c.saveState()
        c.translate(text_x, text_y)
        c.rotate(90)
        c.drawString(0, 0, chave_acesso)
        c.restoreState()

        table_data = []
        for item in itens:
            codigo, conteudo, quantidade = item
            conteudo_quebrado = "\n".join(conteudo[i:i+82] for i in range(0, len(conteudo), 50))
            table_data.append([conteudo_quebrado, quantidade])

        table_width = width * 0.98
        col_widths = [table_width * 0.95, table_width * 0.05]
        table = Table(table_data, colWidths=col_widths)

        style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 18),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('NOSPLIT', (0, 0), (-1, -1)),
            ('WORDWRAP', (0, 0), (-1, -1)),
            ('ROWHEIGHT', (0, 0), (-1, -1), 100),
            ('LEADING', (0, 0), (-1, -1), 20)
        ])
        table.setStyle(style)

        img_height = 0

        pagina_com_imagem = None
        for offset in range(0, doc.page_count - i * 2):
            pagina_atual = i * 2 + offset
            if pagina_atual < doc.page_count:
                page = doc.load_page(pagina_atual)
                if page.get_images():
                    text = page.get_text("text")
                    if not "DANFE" in text:
                        pagina_com_imagem = page
                    break

        if pagina_com_imagem:
            pix = pagina_com_imagem.get_pixmap(alpha=False, dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='JPEG')
            img_bytes.seek(0)
            img_reader = ImageReader(img_bytes)

            margem_direita = 1.5 * cm
            margem_inferior = 0.1 * cm
            img_width = width - margem_direita
            img_height = height - margem_inferior - table.wrap(0, width)[1] - 2 * cm

            c.drawImage(img_reader, 0, height - img_height, width=img_width, height=img_height, preserveAspectRatio=True, anchor='nw')

        if len(table_data) > 4:
            c.showPage()
            
            table.wrapOn(c, width, height)
            table_y = height - table.wrap(0, width)[1] - 1 * cm
            table.drawOn(c, 0.1 * cm, table_y)
        else:
            table.wrapOn(c, width, height)
            table_y = height - img_height - table.wrap(0, width)[1] - 1 * cm
            table.drawOn(c, 0.1 * cm, table_y)

        c.showPage()

    c.save()
    doc.close()
    fim = time.time()
    print(f"PDF gerado com sucesso: {output_pdf} em {fim - inicio} segundos")

if __name__ == '__main__':
    # Registrar limpeza de arquivos temporários quando o servidor for encerrado
    atexit.register(cleanup_temp_files)
    app.run(debug=True, port=5000)