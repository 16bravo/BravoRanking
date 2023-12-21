import kaggle.cli
import sys
import pandas as pd
from pathlib import Path
from zipfile import ZipFile
from tqdm import tqdm
import math
import numpy as np
from dateutil.relativedelta import relativedelta
from datetime import datetime
import sqlite3

## EXTRACT DATA FROM KAGGLE AND EXCEL
# Download data set
# https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017/?select=results.csv
dataset = "martj42/international-football-results-from-1872-to-2017"
sys.argv = [sys.argv[0]] + f"datasets download {dataset}".split(" ")
kaggle.cli.main()

zfile = ZipFile(f"{dataset.split('/')[1]}.zip")

matches = {f.filename:pd.read_csv(zfile.open(f)) for f in zfile.infolist() }["results.csv"]

matches['match_id'] = range(1, len(matches) + 1)

# Match validity filter
# Load data from CSV files
# matches generated with Kaggle API
teams_db = pd.read_excel('teams_db.xlsx')  # Assurez-vous que le fichier est au format Excel

# Merge DataFrames on home_team and away_team columns
merged_df = pd.merge(matches, teams_db[['team', 'tricode']], how='inner', left_on='home_team', right_on='team')
merged_df = pd.merge(merged_df, teams_db[['team', 'tricode']], how='inner', left_on='away_team', right_on='team')

# Filter lines where both teams are valid (non-empty tricode)
valid_matches = merged_df[(merged_df['tricode_x'].notna()) & (merged_df['tricode_y'].notna())]
matches_filtered = valid_matches[['match_id']]
matches = pd.merge(matches, matches_filtered, how='inner', on='match_id')
matches = matches.sort_values(by='match_id', ascending=True)

## LOAD DATA IF EXISTS

matches['home_points_before'] = None
matches['away_points_before'] = None
matches['match_level'] = None
matches['calculated_result'] = None
matches['match_home_points'] = None
matches['match_away_points'] = None
matches['home_points_after'] = None
matches['away_points_after'] = None

database_path = 'data/BravoRanking.db'  
conn = sqlite3.connect(database_path)

# Check if the Rankings table is empty
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM Rankings")
result = cursor.fetchone()

# Create the DataFrame
teams = pd.DataFrame(columns=['team', 'points'])

if result[0] == 0:
    last_date = datetime(1872, 1, 1)
    # Load the DataFrame from the Excel file
    teams_db = pd.read_excel("teams_db.xlsx")
    teams['team'] = teams_db['team']
    teams['points'] = teams_db['base']
    
else:
    # Retrieve the maximum date from the Rankings table
    last_date_query = "SELECT MAX(date) FROM Rankings"
    last_date = pd.read_sql(last_date_query, conn).iloc[0, 0]
    last_year = last_date.year
    last_month = last_date.month
    last_day = last_date.day
    # Load DataFrame from database
    teams_query = f"SELECT team, points FROM Rankings WHERE year = {last_year} AND month = {last_month} AND day = {last_day}"
    teams_db = pd.read_sql(teams_query, conn)
    teams['team'] = teams_db['team']
    teams['points'] = teams_db['points']

conn.close()

## POINTS CALCULATION MATCH BY MATCH

matches['date'] = pd.to_datetime(matches['date'])

matches = matches[matches['date'] > last_date]

for index, match in  tqdm(matches.iterrows(), total=len(matches), desc="Calculating matches points"):
    
    home_team = match['home_team']
    away_team = match['away_team']
    home_score = match['home_score']
    away_score = match['away_score']
    
    # Retrieve the points value for home_team and away_team.
    points_home_team = teams.loc[teams['team'] == home_team, 'points'].values[0]
    points_away_team = teams.loc[teams['team'] == away_team, 'points'].values[0]

    # Point calculations
    calculated_result = ((1/(1+math.exp(-1*(home_score-away_score)/5))-0.5)*21-int(not match['neutral']))*200

    match_level = teams.loc[teams['team'] == home_team, 'points'].values[0]*0.5+teams.loc[teams['team'] == away_team, 'points'].values[0]*0.5

    match_home_points = match_level + calculated_result
    match_away_points = match_level - calculated_result
    
    matches.at[index, 'match_home_points'] = match_home_points
    matches.at[index, 'match_away_points'] = match_away_points
    
    # Update the points in the 'teams' DataFrame with the average over the last 12 months
    for team in [home_team, away_team]:
        team_matches = matches[((matches['home_team'] == team) | (matches['away_team'] == team)) & (matches['date'] <= match['date']) & (matches['date'] > match['date']- relativedelta(years=1))]
        
        team_matches.loc[:, 'match_team_points'] = team_matches.apply(lambda row: row['match_home_points'] if row['home_team'] == team else row['match_away_points'], axis=1)

        team_avg_points = team_matches['match_team_points'].mean()
        
        # Update the value in the 'teams' DataFrame
        teams.loc[teams['team'] == team, 'points'] = team_avg_points
    
    matches.at[index, 'home_points_before'] = points_home_team
    matches.at[index, 'away_points_before'] = points_away_team
    matches.at[index, 'match_level'] = match_level
    matches.at[index, 'calculated_result'] = calculated_result
    matches.at[index, 'home_points_after'] = teams.loc[teams['team'] == home_team, 'points'].values[0]
    matches.at[index, 'away_points_after'] = teams.loc[teams['team'] == away_team, 'points'].values[0]

# Sort the "teams" DataFrame by points in descending order
teams = teams.sort_values(by='points', ascending=False)

# Add a new "ranking" column based on the sorted index
teams['ranking'] = range(1, len(teams) + 1)

## GET POINTS YEAR BY YEAR AND TODAY

start_date = matches['date'].min()
end_date = matches['date'].max()

EOY_dates = pd.date_range(start=start_date, end=end_date, freq='A-DEC') # 'A-DEC' for each December 31st

historical_points = pd.DataFrame({'date': EOY_dates})
historical_points = historical_points.append({'date': pd.Timestamp(datetime.now())}, ignore_index=True)
historical_points = pd.concat([historical_points, pd.DataFrame(columns=teams['team'].unique())], axis=1)

for index, row in tqdm(historical_points.iterrows(), total=len(historical_points), desc="Calculating Historical Points"):
    date = row['date']

    for team in teams['team'].unique():
        team_matches = matches[((matches['home_team'] == team) | (matches['away_team'] == team)) & (matches['date'] <= date)]

        if not team_matches.empty:
            last_points_home = team_matches.iloc[-1]['home_points_after'] if team_matches.iloc[-1]['home_team'] == team else 0
            last_points_away = team_matches.iloc[-1]['away_points_after'] if team_matches.iloc[-1]['away_team'] == team else 0

            last_points = max(last_points_home, last_points_away)

            historical_points.at[index, team] = last_points

## DATA CLEANSING

melted_points = pd.melt(historical_points, id_vars=['date'], var_name='team', value_name='points')
melted_points.sort_values(by=['date', 'team'], inplace=True)

# Deleting empty lines
melted_points = melted_points[melted_points['points'].notna()]

melted_points['date'] = pd.to_datetime(melted_points['date'])
teams_db['startDate'] = pd.to_datetime(teams_db['startDate'])
teams_db['endDate'] = pd.to_datetime(teams_db['endDate'])

merged_data = pd.merge(melted_points, teams_db[['team','startDate','endDate']], on='team')
valid_data = merged_data[((merged_data['date'] >= merged_data['startDate']) | merged_data['startDate'].isna()) &
                         ((merged_data['date'] <= merged_data['endDate']) | merged_data['endDate'].isna())]

ranking_df = valid_data[['date', 'team', 'points']]

ranking_df.loc[:, 'ranking'] = ranking_df.groupby('date')['points'].rank(ascending=False, method='min')

ranking_df.sort_values(by=['date', 'ranking'], inplace=True)

ranking_df['year'] = ranking_df['date'].dt.year
ranking_df['month'] = ranking_df['date'].dt.month
ranking_df['day'] = ranking_df['date'].dt.day
ranking_df['points'] = ranking_df['points'].astype(int)
ranking_df['ranking'] = ranking_df['ranking'].astype(int)

ranking_df = ranking_df[['date', 'year', 'month', 'day', 'team', 'points', 'ranking']]

## DATABASE INSERTION
conn = sqlite3.connect(database_path)
cursor = conn.cursor()

ranking_df.to_sql('Rankings', conn, index=False, if_exists='append')  # Utilisez 'replace' ou 'append' selon votre besoin

conn.commit()
conn.close()