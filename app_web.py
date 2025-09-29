from flask import Flask, request, jsonify, render_template, send_file
import os
import json
from werkzeug.utils import secure_filename
from processor import process_etiqueta

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configurações
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'txt'}

# Criar diretórios se não existirem
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Mapa de produtos (exemplo)
PRODUTOS_MAP = {
    "AM997753439BR": [
        {"sku": "ZX2225_2", "titulo": "Sandália Papete Brilho Luxo Em Eva Com Strass Leve Biaritz", "qtd": 1, "cor": "Preto", "tamanho": "39 BR"}
    ],
    "AM996944264BR": [
        {"sku": "ZX2225_2", "titulo": "Sandália Papete Brilho Luxo Em Eva Com Strass Leve Biaritz", "qtd": 1, "cor": "Nude", "tamanho": "38 BR"},
        {"sku": "ZX2225_2", "titulo": "Sandália Papete Brilho Luxo Em Eva Com Strass Leve Biaritz", "qtd": 1, "cor": "Branco", "tamanho": "39 BR"},
        {"sku": "ZX2225_2", "titulo": "Sandália Papete Brilho Luxo Em Eva Com Strass Leve Biaritz", "qtd": 1, "cor": "Preto", "tamanho": "39 BR"}
    ]
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Nenhum arquivo enviado'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nenhum arquivo selecionado'})
    
    if file and allowed_file(file.filename):
        filepath = None
        try:
            # Salvar arquivo temporariamente
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Processar arquivo
            filename_without_ext = os.path.splitext(filename)[0]
            enhanced_output = os.path.join(OUTPUT_FOLDER, f"{filename_without_ext}_processado.pdf")
            result = process_etiqueta(filepath, PRODUTOS_MAP, enhanced_output)
            
            # Tentar limpar arquivo de upload (não crítico se falhar)
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except (PermissionError, OSError):
                # Arquivo pode estar em uso, ignorar erro
                pass
            
            return jsonify({
                'success': True,
                'result': result,
                'download_url': f'/download/{os.path.basename(enhanced_output)}'
            })
            
        except Exception as e:
            # Tentar limpar arquivo de upload em caso de erro
            try:
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
            except (PermissionError, OSError):
                pass
            
            return jsonify({
                'success': False,
                'error': f'Erro ao processar arquivo: {str(e)}'
            })
    
    return jsonify({'success': False, 'error': 'Tipo de arquivo não permitido'})

@app.route('/demo', methods=['GET'])
def demo():
    try:
        # Conteúdo de demonstração
        demo_content = """
        Rastreamento: AM997753439BR
        Destinatário: João Silva
        Produto: Exemplo Demo
        
        Rastreamento: AM996944264BR  
        Destinatário: Maria Santos
        Produto: Sandália Papete Brilho Luxo Em Eva Com Strass Leve Biaritz
        """
        
        demo_file = os.path.join(UPLOAD_FOLDER, "demo.txt")
        with open(demo_file, 'w', encoding='utf-8') as f:
            f.write(demo_content)
        
        # Processar demonstração
        output_filename = f"demo_processado.pdf"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        result = process_etiqueta(demo_file, PRODUTOS_MAP, output_path)
        
        # Tentar limpar arquivo temporário (não crítico se falhar)
        try:
            if os.path.exists(demo_file):
                os.remove(demo_file)
        except (PermissionError, OSError):
            # Arquivo pode estar em uso, ignorar erro
            pass
        
        return jsonify({
            'success': True,
            'result': result,
            'download_url': f'/download/{os.path.basename(output_path)}'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erro na demonstração: {str(e)}'
        })

@app.route('/download/<filename>')
def download_file(filename):
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'error': 'Arquivo não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': f'Erro ao baixar arquivo: {str(e)}'}), 500

@app.route('/produtos', methods=['GET', 'POST'])
def manage_produtos():
    if request.method == 'GET':
        return jsonify(PRODUTOS_MAP)
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if data:
                PRODUTOS_MAP.update(data)
                return jsonify({'success': True, 'message': 'Produtos atualizados'})
            else:
                return jsonify({'success': False, 'error': 'Dados inválidos'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

@app.route('/api/info')
def api_info():
    return jsonify({
        'app': 'Processador de Etiquetas',
        'version': '1.0',
        'endpoints': {
            '/': 'Interface principal',
            '/upload': 'Upload de arquivos (POST)',
            '/demo': 'Demonstração (GET)',
            '/download/<filename>': 'Download de arquivos processados',
            '/produtos': 'Gerenciar produtos (GET/POST)',
            '/api/info': 'Informações da API'
        }
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)