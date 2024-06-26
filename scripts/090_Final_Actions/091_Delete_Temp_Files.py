import os

folder_path = 'data/temp/'

files_to_delete = ['latest_date.txt','matches.csv','points_history.csv','ranking.csv','teams.csv','fixtures.csv']

for file in files_to_delete:
    full_path = os.path.join(folder_path, file)

    if os.path.exists(full_path):
        os.remove(full_path)
        print(f"File {file} deleted.")
    else:
        print(f"File {file} does not exist.")

kaggle_zip_file = 'all-international-football-results.zip'

if os.path.exists(kaggle_zip_file):
    os.remove(kaggle_zip_file)
    print("Kaggle File deleted.")
else:
    print("Kaggle File does not exist.")