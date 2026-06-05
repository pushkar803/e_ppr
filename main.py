import argparse
import requests, sqlite3
from datetime import date
from datetime import datetime, timedelta, timezone
import requests as rq
import os, json
from fpdf import FPDF
from PIL import Image
import shutil

# app.py
from flask import Flask, request, jsonify, send_file, send_from_directory, abort
from flask_cors import CORS, cross_origin

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

DOWNLOAD_DIRECTORY = os.environ.get("EPPR_DOWNLOAD_DIRECTORY", "files")
DB_NAME = os.environ.get("EPPR_DB_NAME", 'test.db')
SNDND = True
LIFE365 = False
PUBLISHED_DATES_API_KEY = "KTugmCg4FFwIqxxErBF7epCaobnYzURF"
S3_IMAGE_BASE_URL = "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/"
PAPER_CONFIGS = {
	"sandhyanand": {
		"ppr_id": "630",
		"api_url": "https://sandhyanand.epapers.in/api/GetPublishedDates.php",
		"image_base_url": "https://sandhyanand.epapers.in/encyc/",
		"image_base_urls": [
			"https://sandhyanand.epapers.in/encyc/",
			S3_IMAGE_BASE_URL,
		],
		"telegram_prefix": "SND",
		"table_name": "SNDND",
	},
	"life365": {
		"ppr_id": "635",
		"api_url": "https://life365.epapers.in/api/GetPublishedDates.php",
		"image_base_url": S3_IMAGE_BASE_URL,
		"image_base_urls": [S3_IMAGE_BASE_URL],
		"telegram_prefix": "L365",
		"table_name": "LIFE365",
	},
}
DEFAULT_PAPER = "sandhyanand"
DEFAULT_IMAGE_BASE_URL = PAPER_CONFIGS[DEFAULT_PAPER]["image_base_url"]
IST = timezone(timedelta(hours=5, minutes=30))


def resolve_paper_config(paper_name=None, ppr_id=None):
	if paper_name:
		return PAPER_CONFIGS[paper_name]

	if ppr_id:
		ppr_id = str(ppr_id)
		for paper_config in PAPER_CONFIGS.values():
			if paper_config["ppr_id"] == ppr_id:
				return paper_config

	return PAPER_CONFIGS[DEFAULT_PAPER]


def current_ist_date():
	return datetime.now(IST).date()


def build_published_dates_headers(api_url):
	host = api_url.split('/')[2]
	return {
		'authority': host,
		'x-requested-with': 'XMLHttpRequest',
		'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.114 Safari/537.36',
		'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
		'origin': 'https://'+host,
		'referer': 'https://'+host+'/'
	}


def fetch_latest_published_date(paper_name):
	paper_config = PAPER_CONFIGS[paper_name]
	response = requests.request(
		"POST",
		paper_config["api_url"],
		headers=build_published_dates_headers(paper_config["api_url"]),
		data="key="+PUBLISHED_DATES_API_KEY,
		timeout=30,
	)
	response.raise_for_status()
	json_resp = json.loads(response.text)
	latest_date = json_resp[0]['DocumentDate']['date'].split(' ')[0]
	return datetime.strptime(latest_date, '%Y-%m-%d').date()


def check_first_page_image_available(paper_name, published_date):
	paper_config = PAPER_CONFIGS[paper_name]
	context_identifier = published_date.strftime('%Y_%m_%d')
	urls = build_page_image_urls(
		paper_config["image_base_urls"],
		paper_config["ppr_id"],
		context_identifier,
		1,
	)

	for url in urls:
		try:
			with requests.get(url, stream=True, timeout=30) as response:
				response.raise_for_status()
				first_chunk = next(response.iter_content(chunk_size=8192), b'')
				if is_image_response(response, first_chunk):
					print(paper_name+" first image found: "+url)
					return True
				print(paper_name+" first image not found at "+url+" ("+response.headers.get('content-type', '')+")")
		except requests.RequestException as error:
			print(paper_name+" first image check failed at "+url+": "+str(error))

	return False


def ensure_sent_table(conn, table_name):
	conn.execute(
		"""CREATE TABLE IF NOT EXISTS """+table_name+""" (
			ID INTEGER PRIMARY KEY AUTOINCREMENT,
			DATE DATE NOT NULL,
			IsSent INT NOT NULL
		)"""
	)


def has_paper_been_sent(conn, table_name, published_date):
	cursor = conn.cursor()
	cursor.execute(
		"""SELECT IsSent FROM """+table_name+""" WHERE DATE = ? AND IsSent = 1""",
		(published_date,),
	)
	record = cursor.fetchone()
	cursor.close()
	return record is not None


def mark_paper_sent(conn, table_name, published_date):
	conn.execute(
		"""INSERT INTO """+table_name+""" (DATE, IsSent) VALUES (?, ?)""",
		(published_date, 1),
	)
	conn.commit()


def send_latest_paper(paper_name, db_name=DB_NAME, download_directory=DOWNLOAD_DIRECTORY, cleanup=True, target_date=None):
	paper_config = PAPER_CONFIGS[paper_name]
	published_date = target_date or current_ist_date()
	published_date_string = published_date.strftime('%Y-%m-%d')
	print(paper_name+" target_date: "+published_date_string)

	conn = sqlite3.connect(db_name)
	try:
		ensure_sent_table(conn, paper_config["table_name"])
		if has_paper_been_sent(conn, paper_config["table_name"], published_date_string):
			print(paper_name+" "+published_date_string+" already sent")
			return "already_sent"

		if not check_first_page_image_available(paper_name, published_date):
			print(paper_name+" "+published_date_string+" image not found; skipping")
			return "missing"

		context_identifier, pdf_path, folder_path = diver_program(
			published_date,
			paper_config["ppr_id"],
			download_directory=download_directory,
			base_url=paper_config["image_base_url"],
			base_urls=paper_config["image_base_urls"],
		)
		send_to_telegram(paper_config["telegram_prefix"]+"_"+context_identifier+".pdf", pdf_path)
		mark_paper_sent(conn, paper_config["table_name"], published_date_string)
		if cleanup:
			shutil.rmtree(folder_path)
		print(paper_name+" "+published_date_string+" sent to Telegram")
		return "sent"
	finally:
		conn.close()

def is_image_response(response, first_chunk):
	content_type = response.headers.get('content-type', '')
	return content_type.startswith('image/') or first_chunk.startswith(b'\xff\xd8')


def download_file(url, file_path, require_image=False):
	local_filename = file_path
	with requests.get(url, stream=True) as r:
		r.raise_for_status()
		chunks = r.iter_content(chunk_size=8192)
		first_chunk = next(chunks, b'')

		if require_image and not is_image_response(r, first_chunk):
			raise ValueError("URL did not return an image: "+url)

		with open(local_filename, 'wb') as f:
			if first_chunk:
				f.write(first_chunk)
			for chunk in chunks: 
				#if chunk: 
				f.write(chunk)
	return local_filename


def send_to_telegram(file_name, file_path):

	url = "https://api.telegram.org/bot1707372708:AAGjhII7rN-tyV_ILkwou6zY-hsolObXxX0/sendDocument?chat_id=@e_ppr"
	payload={}
	files=[
	  ('document',(file_name,open(file_path,'rb'),'image/jpeg'))
	]
	headers = {}
	response = rq.request("GET", url, headers=headers, data=payload, files=files)
	print(response.text)


def build_page_image_url(base_url, ppr_id, context_identifier, page_number):
	base_url = base_url.rstrip('/')+'/'
	return base_url+str(ppr_id)+"/"+context_identifier.replace('_','/')+"/Mpage_"+str(page_number)+".jpg"


def build_page_image_urls(base_urls, ppr_id, context_identifier, page_number):
	return [
		build_page_image_url(base_url, ppr_id, context_identifier, page_number)
		for base_url in base_urls
	]


def download_page_image(urls, file_path):
	last_error = None
	for url in urls:
		try:
			return download_file(url, file_path, require_image=True)
		except (requests.RequestException, ValueError) as error:
			last_error = error
			print("failed "+url+": "+str(error))

	raise RuntimeError("could not download image page from any source") from last_error


def diver_program(d_obj,ppr_id, download_directory=DOWNLOAD_DIRECTORY, base_url=DEFAULT_IMAGE_BASE_URL, base_urls=None):

	ppr_id = str(ppr_id)
	day = d_obj.strftime("%d")
	mon = d_obj.strftime("%m")
	yer = d_obj.strftime("%Y")

	context_identifier = yer+'_'+mon+'_'+day

	folder_path = os.path.abspath(
		os.path.join(download_directory, ppr_id+"_"+context_identifier)
	)
	pdf_path = os.path.join(folder_path, ppr_id+"_"+context_identifier+'.pdf')

	if os.path.exists(folder_path) == False:
		os.makedirs(folder_path)

	for i in range(1,17):
		print("downloading "+str(i)+" page")

		urls = build_page_image_urls(base_urls or [base_url], ppr_id, context_identifier, i)
		file_path = os.path.join(folder_path, str(i)+'.jpg')
		
		download_page_image(urls, file_path)

	imagelist = []
	for i in range(2,17):
		imagelist.append(os.path.join(folder_path, str(i)+".jpg"))


	#print(imagelist)

	image1 = Image.open(os.path.join(folder_path, "1.jpg"))
	im1 = image1.convert('RGB')

	new_imagelist = []

	for image in imagelist:
		image2 = Image.open(r''+image)
		im2 = image2.convert('RGB')
		new_imagelist.append(im2)

	im1.save(r''+pdf_path,save_all=True, append_images=new_imagelist)
	return context_identifier,pdf_path,folder_path


def parse_download_date(value):
	for date_format in ('%d-%m-%Y', '%Y-%m-%d'):
		try:
			return datetime.strptime(value, date_format).date()
		except ValueError:
			pass

	raise argparse.ArgumentTypeError(
		"date must be in DD-MM-YYYY or YYYY-MM-DD format"
	)


def build_parser():
	parser = argparse.ArgumentParser(
		description="Download e-paper pages for a specific date and save them as a local PDF."
	)
	subparsers = parser.add_subparsers(dest='command')

	download_parser = subparsers.add_parser(
		'download',
		help='download a local PDF for a specific date'
	)
	download_parser.add_argument(
		'download_date',
		type=parse_download_date,
		help='date to download, for example 06-06-2026'
	)
	download_parser.add_argument(
		'--paper',
		choices=sorted(PAPER_CONFIGS.keys()),
		default=None,
		help='paper source to download (default: inferred from ppr id, otherwise sandhyanand)'
	)
	download_parser.add_argument(
		'-p',
		'--ppr-id',
		default=None,
		help='override the paper id for the selected paper'
	)
	download_parser.add_argument(
		'-o',
		'--output-dir',
		default=DOWNLOAD_DIRECTORY,
		help='directory where the downloaded files will be saved (default: files)'
	)
	download_parser.add_argument(
		'--send-telegram',
		action='store_true',
		help='send the generated PDF to Telegram after downloading'
	)

	send_latest_parser = subparsers.add_parser(
		'send-latest',
		help='send today\'s papers to Telegram once per date'
	)
	send_latest_parser.add_argument(
		'--paper',
		choices=sorted(PAPER_CONFIGS.keys()),
		default=None,
		help='paper source to check (default: both papers)'
	)
	send_latest_parser.add_argument(
		'--date',
		type=parse_download_date,
		default=None,
		help='date to check and send, for example 05-05-2026 (default: today in IST)'
	)
	send_latest_parser.add_argument(
		'-o',
		'--output-dir',
		default=DOWNLOAD_DIRECTORY,
		help='directory where temporary downloaded files will be saved (default: files)'
	)
	send_latest_parser.add_argument(
		'--keep-files',
		action='store_true',
		help='keep downloaded files after sending to Telegram'
	)

	return parser


def main(argv=None):
	parser = build_parser()
	args = parser.parse_args(argv)

	if args.command == 'download':
		paper_config = resolve_paper_config(args.paper, args.ppr_id)
		ppr_id = args.ppr_id or paper_config["ppr_id"]
		try:
			context_identifier, pdf_path, folder_path = diver_program(
				args.download_date,
				ppr_id,
				download_directory=args.output_dir,
				base_url=paper_config["image_base_url"],
				base_urls=paper_config["image_base_urls"],
			)
		except Exception as error:
			print("download failed: "+str(error))
			print("pdf was not generated; skipping Telegram send")
			return 1

		print("downloaded "+context_identifier)
		print("pdf: "+pdf_path)
		print("files: "+folder_path)
		if args.send_telegram:
			telegram_file_name = paper_config["telegram_prefix"]+"_"+context_identifier+".pdf"
			send_to_telegram(telegram_file_name, pdf_path)
		return 0

	if args.command == 'send-latest':
		papers = [args.paper] if args.paper else sorted(PAPER_CONFIGS.keys())
		exit_code = 0
		for paper_name in papers:
			try:
				send_latest_paper(
					paper_name,
					download_directory=args.output_dir,
					cleanup=not args.keep_files,
					target_date=args.date,
				)
			except Exception as error:
				print(paper_name+" failed: "+str(error))
				exit_code = 1
		return exit_code

	app.run(threaded=True, port=5000)
	return 0


@app.route('/get-files/<path:path>',methods = ['GET','POST'])
def get_files(path):

    try:
        return send_from_directory(DOWNLOAD_DIRECTORY, path, as_attachment=True)
    except FileNotFoundError:
        abort(404)


@app.route('/get_by_date/', methods=['POST'])
@cross_origin()
def get_by_date():

    date = request.form.get('date')
    print(date)
    ppr_id = request.form.get('ppr_id')
    paper = request.form.get('paper')

    if date and ppr_id:
        date_object = datetime.strptime(date, '%d-%m-%Y').date()
        paper_config = resolve_paper_config(paper, ppr_id)
        context_identifier , pdf_path, folder_path = diver_program(
            date_object,
            ppr_id,
            base_url=paper_config["image_base_url"],
            base_urls=paper_config["image_base_urls"],
        )

        generated_file_link = request.base_url.replace('query','get-files')+context_identifier+"/"+context_identifier+".pdf"
        return jsonify({
            "SUCCESS": generated_file_link
        })

    else:
        return jsonify({
            "ERROR": "no date found, please send a date and ppr_id."
        })

@app.route('/get_todays/', methods=['GET','POST'])
@cross_origin()
def get_todays():

	try:

		conn = sqlite3.connect(DB_NAME)
		cursor = conn.cursor()
		print("Connected database successfully");

		#Sandhyanand
		if SNDND == True:
			print("############ sandhyanand started ###########")

			url = "https://sandhyanand.epapers.in/api/GetPublishedDates.php"
			payload="key=KTugmCg4FFwIqxxErBF7epCaobnYzURF"
			headers = {
			  'authority': 'sandhyanand.epapers.in',
			  'x-requested-with': 'XMLHttpRequest',
			  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.114 Safari/537.36',
			  'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
			  'origin': 'https://sandhyanand.epapers.in',
			  'referer': 'https://sandhyanand.epapers.in/'
			}
			response = requests.request("POST", url, headers=headers, data=payload)
			#print(response.text)
			json_resp = json.loads(response.text)
			#print(json_resp)
			latest_date = json_resp[0]['DocumentDate']['date'].split(' ')[0]
			print(latest_date)
			date_object = datetime.strptime(latest_date, '%Y-%m-%d').date()

			print("checking if already exists...")
			cursor.execute( """SELECT `IsSent` from SNDND where `DATE` = ?""", (latest_date,))
			records = cursor.fetchall()
			print("records: ", str(len(records)))

			if len(records) == 0:
				paper_config = PAPER_CONFIGS["sandhyanand"]
				context_identifier , pdf_path, folder_path = diver_program(
					date_object,
					paper_config["ppr_id"],
					base_url=paper_config["image_base_url"],
					base_urls=paper_config["image_base_urls"],
				)
				send_to_telegram(paper_config["telegram_prefix"]+"_"+context_identifier+".pdf", pdf_path)
				shutil.rmtree(folder_path)
				cursor.execute("""INSERT INTO SNDND (`DATE`,`IsSent`) VALUES (?,?)""",(latest_date,1))
				conn.commit()
			else:
				print("ppr already downloaded.")

			print("############ sandhyanand end ###########")

		#life365
		if LIFE365 == True:
			print("############ life365 started ###########")

			url = "https://life365.epapers.in/api/GetPublishedDates.php"
			payload="key=KTugmCg4FFwIqxxErBF7epCaobnYzURF"
			headers = {
			  'authority': 'life365.epapers.in',
			  'x-requested-with': 'XMLHttpRequest',
			  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.114 Safari/537.36',
			  'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
			  'origin': 'https://life365.epapers.in',
			  'referer': 'https://life365.epapers.in/'
			}
			response = requests.request("POST", url, headers=headers, data=payload)
			#print(response.text)
			json_resp = json.loads(response.text)
			#print(json_resp)
			latest_date = json_resp[0]['DocumentDate']['date'].split(' ')[0]
			print(latest_date)
			date_object = datetime.strptime(latest_date, '%Y-%m-%d').date()

			print("checking if already exists...")
			cursor.execute( """SELECT `IsSent` from LIFE365 where `DATE` = ?""", (latest_date,))
			records = cursor.fetchall()
			print("records: ", str(len(records)))

			if len(records) == 0:
				paper_config = PAPER_CONFIGS["life365"]
				context_identifier , pdf_path, folder_path = diver_program(
					date_object,
					paper_config["ppr_id"],
					base_url=paper_config["image_base_url"],
					base_urls=paper_config["image_base_urls"],
				)
				send_to_telegram(paper_config["telegram_prefix"]+"_"+context_identifier+".pdf", pdf_path)
				shutil.rmtree(folder_path)
				cursor.execute("""INSERT INTO LIFE365 (`DATE`,`IsSent`) VALUES (?,?)""",(latest_date,1))
				conn.commit()
			else:
				print("ppr already downloaded.")

			print("############ life365 end ###########")

			cursor.close()
			if conn:
				conn.close()

		return jsonify({
            "SUCCESS": "found and sent sucess"
        })

	except Exception as e:
		print(e)
		return jsonify({
            "ERROR": "Not Published yet"
        })


@app.route('/')
def index():
    return "<h1>Welcome to eppr server !!</h1>"

if __name__ == '__main__':
    raise SystemExit(main())



