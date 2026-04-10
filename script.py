import os
import pandas as pd
from Bio import Entrez
import re
import requests
from datetime import datetime, timedelta

# Configuration
EMAIL = "your-email@example.com"  # PubMed requires an email for API access
SEARCH_QUERY_PUBMED = '("new species"[Title/Abstract] OR "new genus"[Title/Abstract] OR "new taxon"[Title/Abstract]) AND (fossil OR paleontology)'
SEARCH_QUERY_BIORXIV = 'fossil OR paleontology OR "new species"' # bioRxiv search is simpler
CSV_PATH = "data/fossils.csv"
LOG_PATH = "data/run_log.csv"
SUMMARY_PATH = "data/new_articles_summary.txt"

def search_pubmed():
    Entrez.email = EMAIL
    # Search for articles from the last 7 days (to be more inclusive)
    date_threshold = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
    query = f"({SEARCH_QUERY_PUBMED}) AND ({date_threshold}[Publication Date] : 3000[Publication Date])"
    
    handle = Entrez.esearch(db="pubmed", term=query, retmax=50)
    record = Entrez.read(handle)
    handle.close()
    return record["IdList"]

def fetch_pubmed_details(id_list):
    if not id_list:
        return []
    
    handle = Entrez.efetch(db="pubmed", id=id_list, rettype="xml", retmode="text")
    records = Entrez.read(handle)
    handle.close()
    
    results = []
    for article in records.get("PubmedArticle", []):
        medline = article["MedlineCitation"]
        article_data = medline["Article"]
        
        # Basic Info
        title = article_data.get("ArticleTitle", "N/A")
        doi = "N/A"
        for id_obj in article_data.get("ELocationID", []):
            if id_obj.attributes.get("EIdType") == "doi":
                doi = str(id_obj)
        
        authors = ", ".join([f"{a.get('LastName', '')} {a.get('Initials', '')}" for a in article_data.get("AuthorList", [])])
        pub_date = article_data.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
        pub_date_str = f"{pub_date.get('Year', '')}-{pub_date.get('Month', '01')}-{pub_date.get('Day', '01')}"
        
        abstract = ""
        if "Abstract" in article_data:
            abstract = " ".join(article_data["Abstract"]["AbstractText"])
        
        # Extraction (Heuristics)
        species = extract_species(title, abstract)
        group = extract_group(abstract)
        fossil_date = extract_fossil_date(abstract)
        
        results.append({
            "Source": "PubMed",
            "DOI": doi,
            "Title": title,
            "Authors": authors,
            "Publication Date": pub_date_str,
            "Species": species,
            "Group": group,
            "Fossil Date": fossil_date,
            "Fetched At": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    
    return results

def search_biorxiv():
    today = datetime.now().strftime("%Y-%m-%d")
    last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    url = f"https://api.biorxiv.org/details/biorxiv/{last_week}/{today}/0"
    try:
        response = requests.get(url)
        data = response.json()
        preprints = data.get("collection", [])
        
        results = []
        for p in preprints:
            title = p.get("title", "")
            abstract = p.get("abstract", "")
            
            # Filter by keywords since the API interval returns everything
            if any(kw in (title + abstract).lower() for kw in ["fossil", "paleontology", "new species", "sp. nov."]):
                results.append({
                    "Source": "bioRxiv",
                    "DOI": p.get("doi", "N/A"),
                    "Title": title,
                    "Authors": p.get("authors", "N/A"),
                    "Publication Date": p.get("date", "N/A"),
                    "Species": extract_species(title, abstract),
                    "Group": extract_group(abstract),
                    "Fossil Date": extract_fossil_date(abstract),
                    "Fetched At": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        return results
    except Exception as e:
        print(f"Error searching bioRxiv: {e}")
        return []

def extract_species(title, abstract):
    # Look for patterns like "Name gen. et sp. nov." or "Name sp. nov."
    pattern = r"([A-Z][a-z]+ [a-z]+) (?:gen\. et |sp\. )?nov\."
    match = re.search(pattern, title + " " + abstract)
    return match.group(1) if match else "Unknown"

def extract_group(abstract):
    groups = ["Dinosaur", "Mammal", "Reptile", "Amphibian", "Fish", "Invertebrate", "Plant", "Hominin"]
    for g in groups:
        if g.lower() in abstract.lower():
            return g
    return "Unknown"

def extract_fossil_date(abstract):
    # Look for "Ma" (Million years ago) or Epoch names
    ma_pattern = r"(\d+(?:\.\d+)?\s?Ma)"
    epochs = ["Cretaceous", "Jurassic", "Triassic", "Permian", "Carboniferous", "Devonian", "Silurian", "Ordovician", "Cambrian", "Pleistocene", "Pliocene", "Miocene", "Oligocene", "Eocene", "Paleocene"]
    
    ma_match = re.search(ma_pattern, abstract)
    if ma_match:
        return ma_match.group(1)
    
    for epoch in epochs:
        if epoch.lower() in abstract.lower():
            return epoch
    return "Unknown"

def update_csv(all_details):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    cols = ["Source", "DOI", "Title", "Authors", "Publication Date", "Species", "Group", "Fossil Date", "Fetched At"]
    
    if os.path.exists(CSV_PATH):
        df_existing = pd.read_csv(CSV_PATH)
    else:
        df_existing = pd.DataFrame(columns=cols)
        df_existing.to_csv(CSV_PATH, index=False)

    if not all_details:
        print("No new data found.")
        return 0, []
    
    new_df = pd.DataFrame(all_details)
    all_processed = []
    
    for idx, row in new_df.iterrows():
        # Check if already in the master database (fossils.csv)
        if not df_existing.empty and row["DOI"] in df_existing["DOI"].values:
            first_found = df_existing[df_existing["DOI"] == row["DOI"]]["Fetched At"].iloc[0]
            # Extract just the date if it's a timestamp
            date_str = first_found.split(" ")[0] if " " in first_found else first_found
            status = f"Duplicate (First found: {date_str})"
            processed_row = row.to_dict()
            processed_row["Status"] = status
            all_processed.append(processed_row)
        else:
            status = "New entry"
            processed_row = row.to_dict()
            processed_row["Status"] = status
            all_processed.append(processed_row)
    
    # Identify unique new entries to append to fossils.csv
    new_unique_df = pd.DataFrame([p for p in all_processed if p["Status"] == "New entry"])
    
    if not new_unique_df.empty:
        # Drop Status before adding to fossils.csv
        to_append = new_unique_df.drop(columns=["Status"])
        combined_df = pd.concat([df_existing, to_append]).drop_duplicates(subset=["DOI"], keep="first")
        combined_df.to_csv(CSV_PATH, index=False)
        print(f"Added {len(new_unique_df)} new entries to {CSV_PATH}.")
    else:
        print("No new unique entries to add to fossils.csv.")
    
    return len(new_unique_df), all_processed

def generate_summary(new_entries):
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    if new_entries.empty:
        if os.path.exists(SUMMARY_PATH):
            os.remove(SUMMARY_PATH)
        return
    
    with open(SUMMARY_PATH, "w") as f:
        f.write("New Fossil Articles Found!\n\n")
        f.write("Total: " + str(len(new_entries)) + "\n\n")
        for idx, row in new_entries.iterrows():
            f.write(f"- {row['Title']}\n")
            f.write(f"  Source: {row['Source']}\n")
            f.write(f"  Authors: {row['Authors']}\n")
            f.write(f"  DOI: {row['DOI']}\n")
            f.write(f"  Species: {row['Species']}\n")
            f.write("-" * 20 + "\n")
    print(f"Summary generated at {SUMMARY_PATH}")

def log_run(pubmed_count, biorxiv_count, added_count, all_processed):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    
    entries_to_log = []
    
    if not all_processed:
        # Log a "No articles found" entry if the search yielded nothing
        entries_to_log.append({
            "Run Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Source": "-",
            "DOI": "-",
            "Title": "No articles found",
            "Status": "-",
            "PubMed Found": pubmed_count,
            "bioRxiv Found": biorxiv_count,
            "New Entries Added": 0
        })
    else:
        # Log each found article individually
        for row in all_processed:
            entries_to_log.append({
                "Run Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Source": row['Source'],
                "DOI": row['DOI'],
                "Title": row['Title'],
                "Status": row['Status'],
                "PubMed Found": 0,
                "bioRxiv Found": 0,
                "New Entries Added": 1 if row['Status'] == "New entry" else 0
            })
    
    df_new = pd.DataFrame(entries_to_log)
    
    if os.path.exists(LOG_PATH):
        try:
            df_log = pd.read_csv(LOG_PATH)
            df_log = pd.concat([df_log, df_new], ignore_index=True)
        except Exception:
            df_log = df_new
    else:
        df_log = df_new
    
    cols = ["Run Date", "Source", "DOI", "Title", "Status", "PubMed Found", "bioRxiv Found", "New Entries Added"]
    df_log = df_log[cols]
    
    df_log.to_csv(LOG_PATH, index=False)
    print(f"Log updated at {LOG_PATH}")

if __name__ == "__main__":
    print("Searching PubMed for new fossils...")
    pubmed_ids = search_pubmed()
    pubmed_count = len(pubmed_ids)
    print(f"Found {pubmed_count} PubMed candidates.")
    pubmed_details = fetch_pubmed_details(pubmed_ids)
    
    print("Searching bioRxiv for new preprints...")
    biorxiv_details = search_biorxiv()
    biorxiv_count = len(biorxiv_details)
    print(f"Found {biorxiv_count} bioRxiv candidates.")
    
    all_details = pubmed_details + biorxiv_details
    added_count, all_processed = update_csv(all_details)
    
    # For summary, we still want the new unique entries
    new_entries = pd.DataFrame([p for p in all_processed if p["Status"] == "New entry"])
    generate_summary(new_entries)
    log_run(pubmed_count, biorxiv_count, added_count, all_processed)
