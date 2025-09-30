# processor.py
import re
import io
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# --- Dependências que você deve instalar:
# pip install pdfplumber pytesseract pillow pyzbar python-barcode reportlab
# (instale também o Tesseract no sistema, ex.: Ubuntu: sudo apt-get install tesseract-ocr)

import pdfplumber
from PIL import Image
import pytesseract

try:
    from pyzbar.pyzbar import decode as zbar_decode
except Exception:
    zbar_decode = None

# Code128 com python-barcode
from barcode import Code128
from barcode.writer import ImageWriter

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

TRACKING_RE = re.compile(r"\b([A-Z]{2}\d{9}[A-Z]{2})\b")
CHAVE44_RE = re.compile(r"\b(\d{44})\b", re.MULTILINE)
DEST_HINTS = [r"DESTINAT[ÁA]RIO", r"\bDEST\.\b", r"\bNOME DO DESTINAT[ÁA]RIO\b"]

def read_pdf_text(path: Path) -> List[str]:
    """Extrai texto por página de um PDF (sem OCR)."""
    pages_text = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return pages_text

def ocr_image(image: Image.Image) -> str:
    """OCR com Tesseract."""
    return pytesseract.image_to_string(image, lang="por+eng")

def pdf_to_images(path: Path) -> List[Image.Image]:
    """(Opcional) Converter PDF em imagens para OCR/Barcodes.
    Dica: pode usar pdf2image (poppler) se quiser mais robusto.
    Aqui, tentamos com pdfplumber rasterizando a página."""
    images = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pil = page.to_image(resolution=200).original
            images.append(pil)
    return images

def pdf_to_high_quality_images(path: Path) -> List[Image.Image]:
    """Converter PDF em imagens de alta qualidade para exibição na etiqueta final."""
    images = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            # Usar resolução muito alta para qualidade superior
            pil = page.to_image(resolution=600).original
            images.append(pil)
    return images

def find_tracking(text_pages: List[str]) -> Optional[str]:
    for ptxt in text_pages:
        m = TRACKING_RE.search(ptxt)
        if m:
            return m.group(1)
    return None

def find_destinatario_occurrences(text_pages: List[str]) -> List[Tuple[int, str]]:
    """Retorna [(page_idx, linha_detectada)] onde há pista de destinatário."""
    occ = []
    for i, ptxt in enumerate(text_pages):
        lines = ptxt.splitlines()
        for ln in lines:
            for hint in DEST_HINTS:
                if re.search(hint, ln, flags=re.IGNORECASE):
                    # Próxima linha(s) costuma trazer o nome
                    occ.append((i, ln))
    return occ

def extract_possible_names(text: str) -> List[str]:
    """Heurística simples para capturar nomes próximos a 'Destinatário'."""
    names = []
    lines = text.splitlines()
    for idx, ln in enumerate(lines):
        if any(re.search(h, ln, flags=re.IGNORECASE) for h in DEST_HINTS):
            # pegar algumas linhas seguintes
            window = lines[idx+1: idx+4]
            for w in window:
                # nome sem números, com espaços
                if not re.search(r"\d", w) and 3 <= len(w.strip()) <= 120:
                    names.append(w.strip())
    return names

def find_chave_acesso(text: str) -> Optional[str]:
    m = CHAVE44_RE.search(text.replace(" ", ""))
    return m.group(1) if m else None

def detect_danfe(text_pages: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Retorna (is_danfe, destinatario, chave_acesso).
    Regra: destinatário aparece 2 vezes e na 2ª página/trecho há 'chave de acesso' ou 44 dígitos.
    """
    names_by_page: List[Tuple[int, str]] = []
    for i, ptxt in enumerate(text_pages):
        for name in extract_possible_names(ptxt):
            names_by_page.append((i, name))

    if len(names_by_page) >= 2:
        second_page_idx = names_by_page[1][0]
        # procurar 'chave de acesso' ou 44 dígitos na página da 2ª ocorrência
        page_text = text_pages[second_page_idx]
        if re.search(r"CHAVE\s+DE\s+ACESSO", page_text, flags=re.IGNORECASE) or find_chave_acesso(page_text):
            destinatario = names_by_page[0][1]
            chave = find_chave_acesso(page_text)
            return True, destinatario, chave
    # fallback: às vezes só há 1 ocorrência, mas com 44 dígitos + palavra DANFE
    joined = "\n".join(text_pages)
    if re.search(r"\bDANFE\b", joined, flags=re.IGNORECASE) and find_chave_acesso(joined):
        # tentar achar destinatário
        poss = extract_possible_names(joined)
        destinatario = poss[0] if poss else None
        return True, destinatario, find_chave_acesso(joined)

    return False, None, None

def decode_barcodes_from_images(images: List[Image.Image]) -> List[str]:
    if not zbar_decode:
        return []
    values = []
    for img in images:
        for code in zbar_decode(img):
            try:
                val = code.data.decode("utf-8")
                values.append(val)
            except Exception:
                pass
    return list(dict.fromkeys(values))  # únicos, preservando ordem

def generate_code128_image(data: str) -> Image.Image:
    """Gera Code128 (PNG) para a string (ex.: chave de acesso)."""
    print(f"DEBUG - generate_code128_image recebeu: '{data}' (comprimento: {len(data)})")
    
    # Teste: verificar se todos os dígitos estão presentes
    if len(data) == 44:
        print(f"DEBUG - Primeiros 10 dígitos: {data[:10]}")
        print(f"DEBUG - Últimos 10 dígitos: {data[-10:]}")
        print(f"DEBUG - Valor completo: {data}")
    
    fp = io.BytesIO()
    # Aumentando module_height para tamanho real e font_size para melhor legibilidade
    barcode_obj = Code128(data, writer=ImageWriter())
    print(f"DEBUG - Code128 criado com valor original: '{data}'")
    print(f"DEBUG - Code128 propriedade .code: '{barcode_obj.code}'")
    print(f"DEBUG - Comprimento do código interno: {len(barcode_obj.code)}")
    print(f"DEBUG - Valores são iguais? {data == barcode_obj.code}")
    
    # Verificar se há alguma diferença caractere por caractere
    if data != barcode_obj.code:
        print(f"DEBUG - DIFERENÇA DETECTADA!")
        print(f"DEBUG - Original: '{data}'")
        print(f"DEBUG - Code obj: '{barcode_obj.code}'")
        for i, (c1, c2) in enumerate(zip(data, barcode_obj.code)):
            if c1 != c2:
                print(f"DEBUG - Diferença na posição {i}: '{c1}' vs '{c2}'")
    
    barcode_obj.write(fp, options={
        "module_height": 25.0, 
        "font_size": 14,      # Fonte maior para melhor legibilidade
        "module_width": 0.8,  # Largura das barras mais fina para caber mais dígitos
        "quiet_zone": 2.0,    # Zona silenciosa menor
        "text_distance": 8.0  # Distância maior para evitar sobreposição
    })
    fp.seek(0)
    return Image.open(fp)

def extract_products_without_danfe(text_pages: List[str], tracking_codes: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Extrai produtos do texto OCR quando não há DANFE.
    Lógica simples: após cada tracking code, todos os produtos pertencem àquela etiqueta até o próximo tracking code.
    """
    result = {}
    full_text = '\n'.join(text_pages)
    
    # Inicializar resultado para cada tracking code
    for tracking in tracking_codes:
        result[tracking] = []
    
    lines = full_text.split('\n')
    current_tracking = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Verificar se a linha contém um tracking code
        tracking_match = re.search(r'([A-Z]{2}\d{9}[A-Z]{2})', line)
        if tracking_match:
            found_tracking = tracking_match.group(1)
            if found_tracking in tracking_codes:
                current_tracking = found_tracking
            continue
        
        # Se temos um tracking atual, processar como produto
        if current_tracking:
            # Buscar SKU na linha
            sku_match = re.search(r'SKU:\s*([A-Z0-9_]+)', line, re.IGNORECASE)
            if sku_match:
                sku = sku_match.group(1)
                
                # Buscar nome do produto nas próximas linhas
                product_name = ""
                qtd = 1
                cor = ""
                tamanho = ""
                
                # Verificar as próximas 5 linhas para informações do produto
                for j in range(i + 1, min(i + 6, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    
                    # Parar se encontrarmos outro tracking code
                    if re.search(r'[A-Z]{2}\d{9}[A-Z]{2}', next_line):
                        break
                    
                    # Parar se encontrarmos outro SKU
                    if re.search(r'SKU:', next_line, re.IGNORECASE):
                        break
                    
                    # Buscar nome do produto (linha mais longa sem palavras-chave)
                    if (not product_name and len(next_line) > 10 and 
                        not re.search(r'(quantidade:|cor:|tamanho:|venda:|pack)', next_line, re.IGNORECASE)):
                        product_name = next_line
                    
                    # Buscar quantidade
                    qty_match = re.search(r'Quantidade:\s*(\d+)', next_line, re.IGNORECASE)
                    if qty_match:
                        qtd = int(qty_match.group(1))
                    
                    # Buscar cor
                    cor_match = re.search(r'Cor:\s*(.+?)(?:\n|$)', next_line, re.IGNORECASE)
                    if cor_match:
                        cor = cor_match.group(1).strip()
                    
                    # Buscar tamanho
                    tamanho_match = re.search(r'Tamanho:\s*(.+?)(?:\n|$)', next_line, re.IGNORECASE)
                    if tamanho_match:
                        tamanho = tamanho_match.group(1).strip()
                
                product = {
                    'titulo': product_name if product_name else f"Produto {sku}",
                    'sku': sku,
                    'qtd': qtd,
                    'cor': cor,
                    'tamanho': tamanho
                }
                
                result[current_tracking].append(product)
    
    return result

def compose_output_pdf(out_path: Path,
                       tracking: str,
                       destinatario: Optional[str],
                       produtos: List[Dict[str, Any]],
                       barcode_img: Optional[Image.Image],
                       chave: Optional[str]) -> None:
    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "ETIQUETA COMPOSTA")
    y -= 20

    c.setFont("Helvetica", 12)
    c.drawString(40, y, f"Tracking: {tracking}")
    y -= 16
    if destinatario:
        c.drawString(40, y, f"Destinatário: {destinatario}")
        y -= 16

    if chave:
        c.drawString(40, y, f"Chave de Acesso: {chave}")
        y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Produtos:")
    y -= 16
    c.setFont("Helvetica", 11)
    for p in produtos:
        line = f"• {p.get('titulo','(sem título)')}  (SKU: {p.get('sku','-')}  Qtd: {p.get('qtd',1)})"
        c.drawString(50, y, line)
        y -= 14
        if y < 120:
            c.showPage()
            y = height - 50

    if barcode_img:
        # Rotacionar código de barras para posição vertical
        barcode_img_rotated = barcode_img.rotate(90, expand=True)
        
        # Inserir barcode na lateral superior direita da etiqueta (vertical)
        barcode_width = 120  # Largura aumentada para garantir visibilidade completa dos 44 dígitos
        barcode_height = 300 # Altura aumentada para acomodar 44 dígitos completos
        
        # Posição: lateral superior direita com margem menor
        barcode_x = width - barcode_width - 10  # 10 pontos de margem da direita
        barcode_y = height - barcode_height - 10  # 10 pontos de margem do topo
        

        bio = io.BytesIO()
        barcode_img_rotated.save(bio, format="PNG")
        bio.seek(0)
        c.drawImage(ImageReader(bio), barcode_x, barcode_y, 
                   width=barcode_width, height=barcode_height, 
                   preserveAspectRatio=True, mask='auto')

    c.save()

def compose_output_pdf_multiple(out_path: Path,
                               tracking_info: List[Dict[str, Any]],
                               destinatario: Optional[str],
                               barcode_img: Optional[Image.Image],
                               chave: Optional[str],
                               original_etiqueta_path: Optional[Path] = None,
                               barcode_map: Optional[Dict[str, str]] = None) -> None:
    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    # Converter todas as páginas originais para imagens de alta qualidade
    original_images = []
    etiqueta_images = []  # Apenas páginas de etiquetas (não DANFE)
    
    if original_etiqueta_path and original_etiqueta_path.exists():
        try:
            if original_etiqueta_path.suffix.lower() == ".pdf":
                original_images = pdf_to_high_quality_images(original_etiqueta_path)
                
                # Filtrar apenas páginas de etiquetas (não DANFE)
                # Assumindo que páginas DANFE contêm texto específico
                with pdfplumber.open(str(original_etiqueta_path)) as pdf:
                    for idx, page in enumerate(pdf.pages):
                        page_text = page.extract_text() or ""
                        # Se a página não contém indicadores de DANFE, é uma etiqueta
                        if not any(keyword in page_text.upper() for keyword in ['DANFE', 'DOCUMENTO AUXILIAR', 'NOTA FISCAL ELETRÔNICA']):
                            if idx < len(original_images):
                                etiqueta_images.append(original_images[idx])
                        else:
                            print(f"Página DANFE detectada e removida: página {idx + 1}")
            else:
                # Se for imagem diretamente
                etiqueta_images = [Image.open(original_etiqueta_path)]
        except Exception as e:
            print(f"Erro ao carregar etiquetas originais: {e}")

    # Criar uma página para cada tracking code com sua etiqueta correspondente
    for idx, info in enumerate(tracking_info):
        tracking = info["tracking"]
        produtos = info["produtos"]
        
        # Desenhar a etiqueta original correspondente (1º código = 1ª etiqueta, etc.)
        if idx < len(etiqueta_images):
            try:
                original_img = etiqueta_images[idx]
                
                # Converter para bytes para usar com ImageReader, mantendo qualidade máxima
                img_bytes = io.BytesIO()
                original_img.save(img_bytes, format='PNG', optimize=False, quality=100)
                img_bytes.seek(0)
                img_reader = ImageReader(img_bytes)
                
                # Calcular dimensões para deixar espaço para a tabela
                # Etiqueta ocupa 70% da altura da página
                img_height = height * 0.70
                img_width = width * 0.95
                
                # Centralizar a imagem na parte superior
                x_offset = (width - img_width) / 2
                y_offset = height - img_height - 30  # 30 pontos de margem superior
                
                # Desenhar a etiqueta original
                c.drawImage(img_reader, x_offset, y_offset, 
                          width=img_width, height=img_height, 
                          preserveAspectRatio=True, anchor='c')
                
                # ADICIONAR CÓDIGO DE BARRAS ESPECÍFICO PARA ESTE TRACKING (se disponível)
                current_barcode_img = None
                if barcode_map and tracking in barcode_map:
                    # Gerar código de barras específico para este tracking
                    barcode_value = barcode_map[tracking]
                    print(f"DEBUG - Gerando código de barras específico para {tracking}: {barcode_value}")
                    current_barcode_img = generate_code128_image(barcode_value)
                elif barcode_img:
                    # Fallback para o código de barras padrão
                    current_barcode_img = barcode_img
                
                if current_barcode_img:
                    # Rotacionar código de barras para posição vertical
                    barcode_img_rotated = current_barcode_img.rotate(90, expand=True)
                    
                    # Inserir barcode na lateral superior direita da etiqueta (vertical)
                    barcode_width = 120  # Largura aumentada para garantir visibilidade completa dos 44 dígitos
                    barcode_height = 300 # Altura aumentada para acomodar 44 dígitos completos
                    
                    # Posição: lateral superior direita com margem menor
                    barcode_x = width - barcode_width - 10  # 10 pontos de margem da direita
                    barcode_y = height - barcode_height - 10  # 10 pontos de margem do topo
                    

                    bio = io.BytesIO()
                    barcode_img_rotated.save(bio, format="PNG")
                    bio.seek(0)
                    c.drawImage(ImageReader(bio), barcode_x, barcode_y, 
                               width=barcode_width, height=barcode_height, 
                               preserveAspectRatio=True, mask='auto')
                
            except Exception as e:
                print(f"Erro ao incluir etiqueta {idx + 1}: {e}")

        # Criar tabela com informações do produto específico desta etiqueta
        table_data = []
        
        # Cabeçalho da tabela
        table_data.append(['CÓDIGO/TRACKING', 'PRODUTO/CONTEÚDO', 'QTD'])
        
        # Adicionar produtos deste tracking específico
        for p in produtos:
            titulo = p.get('titulo', '(sem título)')
            sku = p.get('sku', '-')
            qtd = p.get('qtd', 1)
            cor = p.get('cor', '')
            tamanho = p.get('tamanho', '')
            
            # Montar descrição completa do produto
            produto_completo = titulo
            if sku != '-' and sku != 'N/A':
                produto_completo += f"\nSKU: {sku}"
            if cor:
                produto_completo += f"\nCor: {cor}"
            if tamanho:
                produto_completo += f"\nTamanho: {tamanho}"
            
            table_data.append([tracking, produto_completo, str(qtd)])
        
        # Criar tabela com larguras proporcionais
        col_widths = [width * 0.25, width * 0.65, width * 0.10]  # 25%, 65%, 10%
        table = Table(table_data, colWidths=col_widths)
        
        # Estilo da tabela similar ao formato original
        table_style = TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Dados
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Tracking centralizado
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # Produto à esquerda
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Quantidade centralizada
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightblue]),
            
            # Bordas
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            
            # Padding
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ])
        
        table.setStyle(table_style)
        
        # Posicionar a tabela na parte inferior da página
        table_width, table_height = table.wrap(width, height)
        table_x = (width - table_width) / 2  # Centralizar horizontalmente
        table_y = 50  # 50 pontos da margem inferior
        
        # Desenhar a tabela
        table.drawOn(c, table_x, table_y)
        
        # Nova página para o próximo tracking (exceto na última iteração)
        if idx < len(tracking_info) - 1:
            c.showPage()

    # Código de barras agora é adicionado diretamente em cada etiqueta no loop acima
    c.save()

def process_etiqueta(etiqueta_path: str,
                     produtos_map: Dict[str, List[Dict[str, Any]]],
                     out_pdf_path: str = "etiqueta_composta.pdf") -> Dict[str, Any]:
    path = Path(etiqueta_path)
    text_pages = []
    if path.suffix.lower() == ".pdf":
        text_pages = read_pdf_text(path)
        # OCR fallback se muito vazio
        if not any(text_pages):
            imgs = pdf_to_images(path)
            text_pages = [ocr_image(img) for img in imgs]
    else:
        # imagem
        img = Image.open(path)
        text_pages = [ocr_image(img)]

    # Buscar TODOS os tracking codes no texto
    all_tracking_codes = []
    for page in text_pages:
        matches = re.findall(r'[A-Z]{2}\d{9}[A-Z]{2}', page)
        for match in matches:
            if match not in all_tracking_codes:
                all_tracking_codes.append(match)

    # Se não encontrou nenhum, tentar com OCR
    if not all_tracking_codes:
        if path.suffix.lower() == ".pdf":
            imgs = pdf_to_images(path)
            ocr_pages = [ocr_image(img) for img in imgs]
            for page in ocr_pages:
                matches = re.findall(r'[A-Z]{2}\d{9}[A-Z]{2}', page)
                for match in matches:
                    if match not in all_tracking_codes:
                        all_tracking_codes.append(match)

    # Usar o primeiro tracking code como principal (para compatibilidade)
    tracking = all_tracking_codes[0] if all_tracking_codes else None

    # detectar DANFE
    is_danfe, destinatario, chave = detect_danfe(text_pages)

    # tentar ler códigos de barras da imagem (se PDF: rasterizar)
    barcode_values = []
    try:
        imgs = pdf_to_images(path) if path.suffix.lower() == ".pdf" else [Image.open(path)]
        barcode_values = decode_barcodes_from_images(imgs) if imgs else []
    except Exception:
        pass

    # Mapear códigos de barras para tracking codes específicos
    barcode_map = {}  # tracking_code -> barcode_value
    barcode_img = None
    barcode_base64 = None

    # Debug: imprimir valores encontrados
    print(f"DEBUG - Valores de códigos de barras encontrados: {barcode_values}")
    print(f"DEBUG - Chave de acesso extraída: {chave}")
    print(f"DEBUG - É DANFE: {is_danfe}")
    print(f"DEBUG - Tracking codes encontrados: {all_tracking_codes}")
    
    if is_danfe:
        # Encontrar todos os códigos de barras de 44 dígitos
        valid_barcodes = []
        
        # PRIORIDADE 1: Usar a chave extraída do texto (mais confiável)
        if chave:
            valid_barcodes.append(chave)
            print(f"DEBUG - Adicionando chave de acesso extraída: {chave}")
        
        # PRIORIDADE 2: Procurar nos códigos de barras lidos
        for val in barcode_values:
            clean_val = re.sub(r"\D", "", val or "")
            if re.fullmatch(r"\d{44}", clean_val) and clean_val not in valid_barcodes:
                valid_barcodes.append(clean_val)
                print(f"DEBUG - Adicionando código de barras lido: {clean_val}")

        print(f"DEBUG - Códigos de barras válidos encontrados: {valid_barcodes}")
        
        # Mapear códigos de barras para tracking codes baseado na ordem de aparição
        for i, tracking_code in enumerate(all_tracking_codes):
            if i < len(valid_barcodes):
                barcode_map[tracking_code] = valid_barcodes[i]
                print(f"DEBUG - Mapeando {tracking_code} -> {valid_barcodes[i]}")
        
        # Para compatibilidade, gerar uma imagem do primeiro código (será substituída depois)
        if valid_barcodes:
            chosen_bar_val = valid_barcodes[0]
            print(f"DEBUG - Valor inicial escolhido para código de barras: {chosen_bar_val}")
            print(f"DEBUG - Gerando código de barras com valor: {chosen_bar_val}")
            barcode_img = generate_code128_image(chosen_bar_val)
            print(f"DEBUG - Código de barras gerado com sucesso")
            # salvar em base64 também
            bbuf = io.BytesIO()
            barcode_img.save(bbuf, format="PNG")
            barcode_base64 = base64.b64encode(bbuf.getvalue()).decode("utf-8")

    # Coletar TODOS os produtos de TODOS os tracking codes
    all_produtos = []
    all_tracking_info = []
    
    # Verificar se algum tracking code está no mapa de produtos
    has_mapped_products = any(tc in produtos_map and produtos_map[tc] for tc in all_tracking_codes)
    
    if is_danfe or has_mapped_products:
        # Para DANFE ou quando há produtos mapeados, usar o mapa de produtos fornecido
        for tc in all_tracking_codes:
            produtos_tc = produtos_map.get(tc, [])
            if produtos_tc:
                all_tracking_info.append({"tracking": tc, "produtos": produtos_tc})
                all_produtos.extend(produtos_tc)
    else:
        # Para não-DANFE sem produtos mapeados, extrair produtos do próprio texto
        extracted_products = extract_products_without_danfe(text_pages, all_tracking_codes)
        for tc in all_tracking_codes:
            produtos_tc = extracted_products.get(tc, [])
            if produtos_tc:
                all_tracking_info.append({"tracking": tc, "produtos": produtos_tc})
                all_produtos.extend(produtos_tc)

    # Gerar etiqueta composta (PDF) com TODOS os tracking codes e produtos
    compose_output_pdf_multiple(Path(out_pdf_path), all_tracking_info, destinatario, barcode_img, chave, path, barcode_map)

    return {
        "arquivo": str(path.name),
        "tracking_codes": all_tracking_codes,
        "tracking_code": tracking,  # Manter para compatibilidade
        "is_danfe": is_danfe,
        "destinatario": destinatario,
        "chave_acesso": chave,
        "barcode_base64": barcode_base64,
        "produtos": all_produtos,
        "tracking_info": all_tracking_info,
        "saida_pdf": out_pdf_path
    }

# ------------------ EXEMPLO DE USO ------------------
if __name__ == "__main__":
    produtos_map = {
        "AM996944264BR": [
            {"sku": "123", "titulo": "Cabo USB 2m", "qtd": 1},
            {"sku": "456", "titulo": "Fonte 20W", "qtd": 1}
        ]
    }
    result = process_etiqueta("etiqueta.pdf", produtos_map, out_pdf_path="etiqueta_composta.pdf")
    print(result)
