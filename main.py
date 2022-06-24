import requests, sqlite3
from datetime import date
from datetime import datetime, timedelta
import requests as rq
import os, json
from fpdf import FPDF
from PIL import Image
import shutil

# app.py
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS, cross_origin

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

DOWNLOAD_DIRECTORY = "files"
DB_NAME = 'test.db'
SNDND = True
LIFE365 = False

def download_file(url, file_path):
    local_filename = file_path
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
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


def diver_program(d_obj,ppr_id):

	ppr_id = str(ppr_id)
	day = d_obj.strftime("%d")
	mon = d_obj.strftime("%m")
	yer = d_obj.strftime("%Y")

	context_identifier = yer+'_'+mon+'_'+day

	cur_path = os.getcwd()
	folder_path = cur_path+'/files/'+ppr_id+"_"+context_identifier+'/'
	pdf_path = folder_path+ppr_id+"_"+context_identifier+'.pdf'

	if os.path.exists(folder_path) == False:
		os.mkdir(folder_path)

	for i in range(1,17):
		print("downloading "+str(i)+" page")

		url = "https://idocuments.s3.ap-south-1.amazonaws.com/encyc/"+str(ppr_id)+"/"+context_identifier.replace('_','/')+"/Mpage_"+str(i)+".jpg"
		file_path = folder_path+str(i)+'.jpg'
		
		download_file(url, file_path)

	imagelist = []
	for i in range(2,17):
		imagelist.append(folder_path+str(i)+".jpg")


	#print(imagelist)

	image1 = Image.open(r''+folder_path+"1.jpg")
	im1 = image1.convert('RGB')

	new_imagelist = []

	for image in imagelist:
	    image2 = Image.open(r''+image)
	    im2 = image2.convert('RGB')
	    new_imagelist.append(im2)

	im1.save(r''+pdf_path,save_all=True, append_images=new_imagelist)
	return context_identifier,pdf_path,folder_path


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

    if date and ppr_id:
        date_object = datetime.strptime(date, '%d-%m-%Y').date()
        context_identifier , pdf_path, folder_path = diver_program(date_object,ppr_id)

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
				ppr_id = 630
				context_identifier , pdf_path, folder_path = diver_program(date_object,ppr_id)
				send_to_telegram("SND_"+context_identifier+".pdf", pdf_path)
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
				ppr_id = 635
				context_identifier , pdf_path, folder_path = diver_program(date_object,ppr_id)
				send_to_telegram("L365_"+context_identifier+".pdf", pdf_path)
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
    app.run(threaded=True, port=5000)



