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
    # ... existing implementation ...
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
    # ... existing implementation ...
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
    # ... existing implementation ...
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
    # ... existing implementation ...
    ma_pattern = r"(\d+(?:\.\d+)?\s?Ma)"
    epochs = ["Cretaceous", "Jurassic", "Triassic", "Permian", "Carboniferous", "Devonian", "Silurian", "Ordovician", "Cambrian", "Pleistocene", "Pliocene", "Miocene", "Oligocene", "Eocene", "Paleocene"]
    
    ma_match = re.search(ma_pattern, abstract)
    if ma_match:
        return ma_match.group(1)
    
    for epoch in epochs:
        if epoch.lower() in abstract.lower():
            return epoch
    return "Unknown"

def update_csv(new_data):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    cols = ["Source", "DOI", "Title", "Authors", "Publication Date", "Species", "Group", "Fossil Date", "Fetched At"]
    
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        if "Source" not in df.columns:
            df.insert(0, "Source", "PubMed")
    else:
        df = pd.DataFrame(columns=cols)
        df.to_csv(CSV_PATH, index=False) # Ensure file exists even if empty

    article_status_map = {} # DOI -> {"status": ..., "first_found": ...}

    if not new_data:
        print("No new data found.")
        return article_status_map
    
    new_df = pd.DataFrame(new_data)
    
    if not df.empty and "DOI" in df.columns:
        existing_dois_map = df.dropna(subset=["DOI"]).set_index("DOI")["Fetched At"].to_dict()
    else:
        existing_dois_map = {}
        
    unique_new_df = new_df.drop_duplicates(subset=["DOI"], keep="first")
    
    for _, row in unique_new_df.iterrows():
        doi = row["DOI"]
        if doi in existing_dois_map:
            article_status_map[doi] = {
                "status": f"Duplicate (First found: {existing_dois_map[doi]})",
                "first_found": existing_dois_map[doi]
            }
        else:
            article_status_map[doi] = {
                "status": "New entry",
                "first_found": row["Fetched At"]
            }
            
    added_df = unique_new_df[~unique_new_df["DOI"].isin(existing_dois_map.keys())]
    
    combined_df = pd.concat([df, added_df]).drop_duplicates(subset=["DOI"], keep="first")
    
    added_count = len(combined_df) - len(df)
    if added_count > 0:
        combined_df.to_csv(CSV_PATH, index=False)
        print(f"Added {added_count} new entries.")
    else:
        print("No new unique entries to add.")
        
    return article_status_map

def log_run(run_date, all_details, article_status_map):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    
    log_entries = []
    
    if not all_details:
        log_entries.append({
            "Run Date": run_date,
            "Source": "N/A",
            "DOI": "N/A",
            "Title": "N/A",
            "Status": "N/A"
        })
    else:
        for detail in all_details:
            doi = detail.get("DOI", "N/A")
            status_info = article_status_map.get(doi, {"status": "Unknown"})
                
            log_entries.append({
                "Run Date": run_date,
                "Source": detail.get("Source", "N/A"),
                "DOI": doi,
                "Title": detail.get("Title", "N/A"),
                "Status": status_info["status"]
            })
            
    df_new = pd.DataFrame(log_entries)
    
    if os.path.exists(LOG_PATH):
        df_log = pd.read_csv(LOG_PATH)
        # Handle migration if column name changed
        if "New entries added" in df_log.columns:
            df_log = df_log.rename(columns={"New entries added": "Status"})
        elif "New Entries Added" in df_log.columns:
            df_log = df_log.rename(columns={"New Entries Added": "Status"})
        df_log = pd.concat([df_log, df_new], ignore_index=True)
    else:
        df_log = df_new
    
    df_log.to_csv(LOG_PATH, index=False)
    print(f"Log updated at {LOG_PATH}")

if __name__ == "__main__":
    run_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
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
    article_status_map = update_csv(all_details)
    
    log_run(run_date, all_details, article_status_map)

    # Generate summary for email notifications if new articles found
    new_articles = []
    for detail in all_details:
        doi = detail.get("DOI")
        if article_status_map.get(doi, {}).get("status") == "New entry":
            link = f"https://doi.org/{doi}" if doi and doi != "N/A" else "No DOI available"
            new_articles.append(f"- {detail.get('Title')}\n  Source: {detail.get('Source')}\n  Link: {link}")
    
    summary_path = "data/new_articles_summary.txt"
    if new_articles:
        with open(summary_path, "w") as f:
            f.write("A new fossil publication was found!\n\n")
            f.write("\n".join(new_articles))
            f.write("\n\nCheck the full log in the repository.")
        print(f"New articles summary created at {summary_path}")
    elif os.path.exists(summary_path):
        os.remove(summary_path) # Ensure old summaries aren't reused
