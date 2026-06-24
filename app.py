from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import zipfile
import tempfile
import shutil
from tempfile import NamedTemporaryFile
from pathlib import Path
from io import BytesIO
import sys
import xml.etree.ElementTree as ET

# ====================================
# PYINSTALLER
# ====================================

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

# ====================================
# APP
# ====================================

app = FastAPI(
    title="XML Flatten ZIP Extractor"
)

app.mount(
    "/static",
    StaticFiles(
        directory=str(BASE_DIR / "static")
    ),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

MAX_FILE_SIZE_MB = 250
MAX_ZIP_DEPTH = 5
ALLOWED_EXTENSION = ".zip"

# ====================================
# HOME
# ====================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )

# ====================================
# HELPERS
# ====================================

def normalize_rut(value):

    if not value:
        return ""

    value = ''.join(
        filter(str.isdigit, value)
    )

    return value.lstrip("0")


def clean_tag(tag):

    tag = tag.lower()

    tag = tag.split("}")[-1]

    if ":" in tag:
        tag = tag.split(":")[-1]

    return tag


def extract_possible_ruts(root):

    found = []

    valid_tags = {
        "rucemisor",
        "rutemisor",
        "rucrecep",
        "rutrecep",
        "docrecep",
        "rutreceptor"
    }

    for elem in root.iter():

        try:

            tag = clean_tag(elem.tag)

            if tag in valid_tags:

                if elem.text:

                    normalized = normalize_rut(
                        elem.text
                    )

                    if normalized:

                        found.append(
                            (
                                tag,
                                normalized
                            )
                        )

        except Exception:
            pass

    return found


def has_tipo_cfe(root):

    for elem in root.iter():

        try:

            tag = clean_tag(elem.tag)

            if tag == "tipocfe":

                if elem.text:
                    return True

        except Exception:
            pass

    return False

# ====================================
# EXTRAER XML RECURSIVO
# ====================================

def extract_xml_files_from_zip(
    zip_file,
    password="",
    depth=0
):

    if depth > MAX_ZIP_DEPTH:
        return

    try:

        for file_info in zip_file.infolist():

            filename = file_info.filename

            lower_name = filename.lower()

            # ZIP Slip
            if ".." in filename:
                continue

            # ====================================
            # XML
            # ====================================

            if lower_name.endswith(".xml"):

                try:

                    with zip_file.open(
                        file_info,
                        pwd=password.encode()
                        if password
                        else None
                    ) as source:

                        xml_bytes = source.read()

                    yield (
                        Path(filename).name,
                        xml_bytes
                    )

                except Exception:
                    continue

            # ====================================
            # ZIP INTERNO
            # ====================================

            elif lower_name.endswith(".zip"):

                try:

                    with zip_file.open(
                        file_info,
                        pwd=password.encode()
                        if password
                        else None
                    ) as nested_zip_file:

                        nested_zip_bytes = (
                            nested_zip_file.read()
                        )

                    nested_zip_buffer = BytesIO(
                        nested_zip_bytes
                    )

                    with zipfile.ZipFile(
                        nested_zip_buffer,
                        'r'
                    ) as nested_zip:

                        yield from extract_xml_files_from_zip(
                            nested_zip,
                            password=password,
                            depth=depth + 1
                        )

                except Exception:
                    continue

    except Exception:
        return

# ====================================
# CLASIFICADOR
# ====================================

def classify_xml(xml_bytes, rut):        

    try:

        rut = normalize_rut(rut)

        xml_text = xml_bytes.decode(
            "utf-8",
            errors="ignore"
        )

        lower_xml = xml_text.lower()

        # ====================================
        # REPORTES DGI
        # ====================================

        if (
            "<reporte" in lower_xml
            or "efacrecepcionreporte" in lower_xml
        ):        
            return "otros"

        # ====================================
        # SOAP DGI
        # ====================================

        if (
            "efacrecepcionsobre" in lower_xml
            or "<envelope" in lower_xml
            or "schemas.xmlsoap.org" in lower_xml
        ):
            return "soap_dgi"

        # ====================================
        # SOBRES
        # ====================================

        is_sobre = (
            "enviocfe_entreempresas" in lower_xml
            or "<enviocfe" in lower_xml
            or "<caratula" in lower_xml
        )

        # ====================================
        # PARSE XML
        # ====================================

        root = ET.fromstring(xml_bytes)

        ruts = extract_possible_ruts(root)

        emisor = None
        receptor = None

        for tag_name, value in ruts:

            if tag_name in [
                "rucemisor",
                "rutemisor"
            ]:
                emisor = value

            if tag_name in [
                "rucrecep",
                "rutrecep",
                "docrecep",
                "rutreceptor"
            ]:
                receptor = value

        # ====================================
        # SOBRES
        # ====================================

        if is_sobre:

            if emisor == rut:
                return "sobres_emitidos"

            if receptor == rut:
                return "sobres_recibidos"

            return "sobres_recibidos"

        # ====================================
        # CFE DIRECTOS
        # ====================================

        if emisor == rut:
            return "emitidos"

        if receptor == rut:
            return "recibidos"


        # ====================================
        # OTROS
        # ====================================

        return "otros"

    except Exception:
        return "otros"

# ====================================
# UPLOAD
# ====================================

@app.post("/upload")
async def upload_zip(
    rut: str = Form(...),
    password: str = Form(""),
    file: UploadFile = File(...)
):

    rut = normalize_rut(rut)

    if not rut:

        return JSONResponse(
            status_code=400,
            content={
                "error":
                "El RUT ingresado no es válido"
            }
        )

    if not file.filename.lower().endswith(
        ALLOWED_EXTENSION
    ):

        return JSONResponse(
            status_code=400,
            content={
                "error":
                "Solo se permiten ZIP"
            }
        )

    with tempfile.TemporaryDirectory() as temp_dir:

        temp_path = Path(temp_dir)

        input_zip_path = temp_path / "input.zip"

        # ====================================
        # GUARDAR ZIP
        # ====================================

        with open(input_zip_path, "wb") as buffer:

            shutil.copyfileobj(
                file.file,
                buffer
            )

        # ====================================
        # VALIDAR TAMAÑO
        # ====================================

        size_mb = (
            input_zip_path.stat().st_size
            / (1024 * 1024)
        )

        if size_mb > MAX_FILE_SIZE_MB:

            return JSONResponse(
                status_code=400,
                content={
                    "error":
                    f"Máximo {MAX_FILE_SIZE_MB} MB"
                }
            )

        # ====================================
        # LEER ZIP RECURSIVO
        # ====================================

        xml_entries = []

        try:

            with zipfile.ZipFile(
                input_zip_path,
                'r'
            ) as zip_ref:

                xml_entries = list(
                    extract_xml_files_from_zip(
                        zip_ref,
                        password=password
                    )
                )

        except zipfile.BadZipFile:

            return JSONResponse(
                status_code=400,
                content={
                    "error":
                    "ZIP corrupto"
                }
            )

        if not xml_entries:

            return JSONResponse(
                status_code=400,
                content={
                    "error":
                    "No se encontraron XML"
                }
            )

        # ====================================
        # CATEGORÍAS
        # ====================================

        categories = {
            "emitidos":
                temp_path / "EMITIDOS.zip",

            "recibidos":
                temp_path / "RECIBIDOS.zip",

            "sobres_emitidos":
                temp_path / "SOBRES_EMITIDOS.zip",

            "sobres_recibidos":
                temp_path / "SOBRES_RECIBIDOS.zip",

            "soap_dgi":
                temp_path / "SOAP_DGI.zip",

            "otros":
                temp_path / "OTROS.zip"
        }

        zip_map = {}

        for key, path in categories.items():

            zip_map[key] = zipfile.ZipFile(
                path,
                'w',
                zipfile.ZIP_DEFLATED
            )

        used_names = {
            key: {}
            for key in categories.keys()
        }

        # ====================================
        # VALIDACIÓN RUT
        # ====================================

        rut_match_count = 0

        # ====================================
        # PROCESAR XML
        # ====================================

        try:

            for original_name, xml_bytes in xml_entries:

                # ====================================
                # CLASIFICAR
                # ====================================

                category = classify_xml(
                    xml_bytes,
                    rut
                )

                # ====================================
                # VALIDAR RUT
                # ====================================

                if category in [
                    "emitidos",
                    "recibidos",
                    "sobres_emitidos",
                    "sobres_recibidos"
                ]:

                    rut_match_count += 1

                final_name = original_name

                # ====================================
                # DUPLICADOS
                # ====================================

                if (
                    final_name.lower()
                    in used_names[category]
                ):

                    used_names[category][
                        final_name.lower()
                    ] += 1

                    stem = Path(
                        final_name
                    ).stem

                    suffix = Path(
                        final_name
                    ).suffix

                    final_name = (
                        f"{stem}_"
                        f"{used_names[category][final_name.lower()]}"
                        f"{suffix}"
                    )

                else:

                    used_names[category][
                        final_name.lower()
                    ] = 0

                # ====================================
                # GUARDAR XML
                # ====================================

                zip_map[category].writestr(
                    final_name,
                    xml_bytes
                )

        finally:

            for z in zip_map.values():
                z.close()

        # ====================================
        # VALIDAR RUT FINAL
        # ====================================

        if rut_match_count == 0:

            return JSONResponse(
                status_code=400,
                content={
                    "error":
                    (
                        "El RUT ingresado no coincide "
                        "con los documentos del ZIP"
                    )
                }
            )

        # ====================================
        # ZIP FINAL
        # ====================================

        final_zip_name = (
            f"RESULTADO-{rut}.zip"
        )

        temp_output = NamedTemporaryFile(
            delete=False,
            suffix=".zip"
        )

        final_zip_path = Path(
            temp_output.name
        )

        temp_output.close()

        with zipfile.ZipFile(
            final_zip_path,
            'w',
            zipfile.ZIP_DEFLATED
        ) as final_zip:

            for path in categories.values():

                if path.exists():

                    final_zip.write(
                        path,
                        arcname=path.name
                    )

    return FileResponse(
        path=final_zip_path,
        filename=final_zip_name,
        media_type='application/zip'
    )

# ====================================
# HEALTH
# ====================================

@app.get("/health")
async def health():

    return {
        "status": "ok"
    }