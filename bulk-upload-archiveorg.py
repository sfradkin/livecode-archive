from internetarchive import upload
import csv
import configparser

config = configparser.ConfigParser()
config.read('live-code-uploader.ini')
archive_org_config = config['archive.org.upload']

with open(archive_org_config['csv.location'], mode='r') as csv_file:
    csv_reader = csv.reader(csv_file)
    for row in csv_reader:

        # file id, file location, title, creator, date recorded, the rest of the columns are subject tags
        # also need prefix for the id, html wrapper around description, mediatype=movies, collection=toplap, licenseurl=https://creativecommons.org/licenses/by-nc-sa/4.0/

        item_prefix = 'algofive-'
        html_wrapper_pre = '<span style="font-family:Roboto, Noto, sans-serif;font-size:15px;white-space:pre-wrap;">Algofive live performance by '
        html_wrapper_post = '</span>'

        file_id = item_prefix + row[0]
        file_loc = row[1]
        title = row[2]
        description = html_wrapper_pre + row[3] + html_wrapper_post
        creator = row[3]
        date_rec = row[4]
        subjects = []
        collections = []

        for n in range(5, len(row)):
            subjects.append(row[n])

        collections.append('toplap')
        if archive_org_config['test']:
            collections.append('test_collection')

        try:

            # 'identifier': 'equinox2020-0001', 'mediatype': 'movies', 'collection': ['toplap', 'computersandtechvideos'], 
            # 'creator': '0001', 'date': '2020-03-19', 'description': '<span style="font-family:Roboto, Noto, sans-serif;font-size:15px;white-space:pre-wrap;">Eulerroom Equinox 2020 live performance by 0001 from Sheffield\n\nGritty noise in crystal-clear surround</span>', 
            # 'licenseurl': 'https://creativecommons.org/licenses/by-nc-sa/4.0/', 'scanner': 'Internet Archive HTML5 Uploader 1.6.4',
            #  'subject': ['eulerroom', 'toplap', 'equinox2020', 'live coding', '0001'], 'title': 'Eulerroom Equinox 2020 - 0001 - 19 March 2020 21:00',
            #  'uploader': 'scott@fradkin.com', 'publicdate': '2020-04-11 22:25:32', 'addeddate': '2020-04-11 22:25:32'}


            meta_data = dict(mediatype='movies', collection=collections, creator=creator, date=date_rec, description=description,
                            licenseurl='https://creativecommons.org/licenses/by-nc-sa/4.0/', subject=subjects, title=title)

            print(f'uploading file: {file_id}')

            result = upload(file_id, files=[file_loc], metadata=meta_data, verbose=True)

            print(f'completed uploading file: {file_id}')
        except Exception as e:
            print(f'An error occurred: {e}')
            pass
