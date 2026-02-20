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
    # bioRxiv API: https://api.biorxiv.org/details/publisher/interval/yyyy-mm-dd/yyyy-mm-dd/cursor
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

def update_csv(new_data):
    if not new_data:
        print("No new data found.")
        return False
    
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    
    cols = ["Source", "DOI", "Title", "Authors", "Publication Date", "Species", "Group", "Fossil Date", "Fetched At"]
    
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        # Ensure 'Source' column exists for older files
        if "Source" not in df.columns:
            df.insert(0, "Source", "PubMed")
    else:
        df = pd.DataFrame(columns=cols)
    
    new_df = pd.DataFrame(new_data)
    
    # Merge and deduplicate by DOI
    combined_df = pd.concat([df, new_df]).drop_duplicates(subset=["DOI"], keep="first")
    
    if len(combined_df) > len(df):
        combined_df.to_csv(CSV_PATH, index=False)
        print(f"Added {len(combined_df) - len(df)} new entries.")
        return True
    else:
        print("No new unique entries to add.")
        return False

if __name__ == "__main__":
    print("Searching PubMed for new fossils...")
    pubmed_ids = search_pubmed()
    print(f"Found {len(pubmed_ids)} PubMed candidates.")
    pubmed_details = fetch_pubmed_details(pubmed_ids)
    
    print("Searching bioRxiv for new preprints...")
    biorxiv_details = search_biorxiv()
    print(f"Found {len(biorxiv_details)} bioRxiv candidates.")
    
    all_details = pubmed_details + biorxiv_details
    update_csv(all_details)
