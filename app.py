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


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


@app.post("/upload")
async def upload_zip(
    rut: str = Form(...),
    file: UploadFile = File(...)
):

    # Limpiar RUT
    rut = ''.join(filter(str.isdigit, rut))

    if not rut:
        return JSONResponse(
            status_code=400,
            content={"error": "El RUT ingresado no es válido"}
        )

    # Validar extensión
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

        # Leer XMLs directamente desde el ZIP
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

                    # Detectar XMLs
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

        # Crear ZIP plano
        output_zip_name = f"xml_flat_{uuid.uuid4().hex}.zip"
        output_zip_path = temp_path / output_zip_name

        used_names = {}

        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as output_zip:

            with zipfile.ZipFile(input_zip_path, 'r') as input_zip:

                for xml_file in xml_entries:

                    original_name = Path(xml_file.filename).name
                    final_name = original_name

                    # Manejo de nombres duplicados
                    if final_name.lower() in used_names:

                        used_names[final_name.lower()] += 1

                        stem = Path(final_name).stem
                        suffix = Path(final_name).suffix

                        final_name = f"{stem}_{used_names[final_name.lower()]}{suffix}"

                    else:
                        used_names[final_name.lower()] = 0

                    # Streaming interno por bloques
                    with input_zip.open(xml_file) as source:

                        with output_zip.open(final_name, 'w') as target:

                            while True:

                                chunk = source.read(1024 * 64)

                                if not chunk:
                                    break

                                target.write(chunk)

        # Carpeta salida
        final_output_dir = BASE_DIR / "generated"
        final_output_dir.mkdir(exist_ok=True)

        final_output_path = final_output_dir / output_zip_name

        shutil.copy(output_zip_path, final_output_path)

    # Descargar ZIP final
    return FileResponse(
        path=final_output_path,
        filename=f"CFE-{rut}.zip",
        media_type='application/zip'
    )


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }