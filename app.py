from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import zipfile
import tempfile
import shutil
from pathlib import Path
import uuid
import sys
import xml.etree.ElementTree as ET

# Compatibilidad con PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="XML Flatten ZIP Extractor")

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

MAX_FILE_SIZE_MB = 80
ALLOWED_EXTENSION = ".zip"

# Tipos CFE EMITIDOS
TIPOS_EMITIDOS = {
    "101",  # eFactura
    "102",  # Nota de Crédito eFactura
    "103",  # Nota de Débito eFactura
    "111",  # eTicket
    "112",  # Nota de Crédito eTicket
    "113",  # Nota de Débito eTicket
    "181",  # eRemito
    "182",  # Nota Crédito eRemito
    "183"   # Nota Débito eRemito
}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


def find_tipo_cfe(root):

    for elem in root.iter():

        tag = elem.tag.lower()

        if tag.endswith("tipocfe"):

            if elem.text:
                return elem.text.strip()

    return None


def classify_xml(xml_bytes):

    try:

        xml_text = xml_bytes.decode(
            "utf-8",
            errors="ignore"
        )

        # Detectar sobres
        if (
            "EnvioCFE" in xml_text
            or "Caratula" in xml_text
        ):
            return "sobres"

        root = ET.fromstring(xml_bytes)

        tipo_cfe = find_tipo_cfe(root)

        # Emitidos
        if tipo_cfe in TIPOS_EMITIDOS:
            return "emitidos"

        # Recibidos
        if (
            "acuse" in xml_text.lower()
            or "recepcion" in xml_text.lower()
            or "respuesta" in xml_text.lower()
            or "rechazo" in xml_text.lower()
        ):
            return "recibidos"

        # Si tiene estructura CFE pero no tipo conocido
        if tipo_cfe:
            return "emitidos"

        return "otros"

    except Exception:
        return "otros"


@app.post("/upload")
async def upload_zip(
    rut: str = Form(...),
    file: UploadFile = File(...)
):

    # Limpiar RUT para nombre archivo
    rut = ''.join(filter(str.isdigit, rut))

    if not rut:
        return JSONResponse(
            status_code=400,
            content={"error": "El RUT ingresado no es válido"}
        )

    # Validar ZIP
    if not file.filename.lower().endswith(ALLOWED_EXTENSION):
        return JSONResponse(
            status_code=400,
            content={"error": "Solo se permiten archivos ZIP"}
        )

    with tempfile.TemporaryDirectory() as temp_dir:

        temp_path = Path(temp_dir)

        input_zip_path = temp_path / "input.zip"

        # Guardar ZIP subido
        with open(input_zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Validar tamaño
        size_mb = input_zip_path.stat().st_size / (1024 * 1024)

        if size_mb > MAX_FILE_SIZE_MB:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"El archivo supera el límite de {MAX_FILE_SIZE_MB} MB"
                }
            )

        # Buscar XMLs
        xml_entries = []

        try:

            with zipfile.ZipFile(input_zip_path, 'r') as zip_ref:

                for file_info in zip_ref.infolist():

                    # Protección ZIP Slip
                    if ".." in file_info.filename:

                        return JSONResponse(
                            status_code=400,
                            content={"error": "ZIP inválido o inseguro"}
                        )

                    if file_info.filename.lower().endswith('.xml'):
                        xml_entries.append(file_info)

        except zipfile.BadZipFile:

            return JSONResponse(
                status_code=400,
                content={"error": "El archivo ZIP está corrupto"}
            )

        if not xml_entries:

            return JSONResponse(
                status_code=400,
                content={"error": "No se encontraron archivos XML"}
            )

        # ZIPs internos
        emitidos_path = temp_path / "EMITIDOS.zip"
        recibidos_path = temp_path / "RECIBIDOS.zip"
        sobres_path = temp_path / "SOBRES.zip"
        otros_path = temp_path / "OTROS.zip"

        zip_map = {
            "emitidos": zipfile.ZipFile(
                emitidos_path,
                'w',
                zipfile.ZIP_DEFLATED
            ),
            "recibidos": zipfile.ZipFile(
                recibidos_path,
                'w',
                zipfile.ZIP_DEFLATED
            ),
            "sobres": zipfile.ZipFile(
                sobres_path,
                'w',
                zipfile.ZIP_DEFLATED
            ),
            "otros": zipfile.ZipFile(
                otros_path,
                'w',
                zipfile.ZIP_DEFLATED
            )
        }

        used_names = {
            "emitidos": {},
            "recibidos": {},
            "sobres": {},
            "otros": {}
        }

        try:

            with zipfile.ZipFile(input_zip_path, 'r') as input_zip:

                for xml_file in xml_entries:

                    original_name = Path(
                        xml_file.filename
                    ).name

                    # Leer XML completo
                    with input_zip.open(xml_file) as source:
                        xml_bytes = source.read()

                    # Clasificar
                    category = classify_xml(xml_bytes)

                    final_name = original_name

                    # Manejo duplicados
                    if final_name.lower() in used_names[category]:

                        used_names[category][final_name.lower()] += 1

                        stem = Path(final_name).stem
                        suffix = Path(final_name).suffix

                        final_name = (
                            f"{stem}_"
                            f"{used_names[category][final_name.lower()]}"
                            f"{suffix}"
                        )

                    else:

                        used_names[category][final_name.lower()] = 0

                    # Guardar XML
                    zip_map[category].writestr(
                        final_name,
                        xml_bytes
                    )

        finally:

            for z in zip_map.values():
                z.close()

        # ZIP final contenedor
        final_zip_name = f"RESULTADO-{rut}.zip"
        final_zip_path = temp_path / final_zip_name

        with zipfile.ZipFile(
            final_zip_path,
            'w',
            zipfile.ZIP_DEFLATED
        ) as final_zip:

            for internal_zip in [
                emitidos_path,
                recibidos_path,
                sobres_path,
                otros_path
            ]:

                if internal_zip.exists():

                    final_zip.write(
                        internal_zip,
                        arcname=internal_zip.name
                    )

        # Carpeta salida
        final_output_dir = BASE_DIR / "generated"
        final_output_dir.mkdir(exist_ok=True)

        final_output_path = final_output_dir / final_zip_name

        shutil.copy(
            final_zip_path,
            final_output_path
        )

    return FileResponse(
        path=final_output_path,
        filename=final_zip_name,
        media_type='application/zip'
    )


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }