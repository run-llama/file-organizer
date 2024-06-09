from dotenv import load_dotenv
load_dotenv()
import os
import sys
import json
import argparse
import tiktoken
import pprint
from llama_index.core import Settings, SimpleDirectoryReader, Document
from llama_index.llms.openai import OpenAI
from llama_index.multi_modal_llms.openai import OpenAIMultiModal
from llama_index.core.agent import AgentRunner
from llama_index.agent.lats import LATSAgentWorker
from llama_index.core.schema import ImageDocument

MIN_FILES_PER_CATEGORY = 3

def get_files_in_folder(folder, recursive=True):
    """Gets a list of all the files in specified folder, recursively"""
    file_paths = []
    with open("db/auto_generated_folders.json", 'r', encoding='utf-8') as file:
        auto_generated_folders = json.load(file)
    
    try:
        # List all files and directories in the given folder
        with os.scandir(folder) as entries:
            for entry in entries:
                path = f"{folder}/{entry.name}"
                if entry.is_dir():
                    if (path in auto_generated_folders):
                        if(recursive):
                            file_paths.extend(get_files_in_folder(path))
                        else:
                            print(f"Not recursing into {path}")
                    else:
                        print(f"Skipping manually-created folder: {path}")
                else:
                    file_paths.append(path)
    except FileNotFoundError:
        print(f"The folder '{folder}' does not exist.")
    except PermissionError:
        print(f"Permission denied to access '{folder}'.")
    return file_paths

def sliceUntilFits(string, max_tokens):
    enc = tiktoken.encoding_for_model("gpt-4o")
    while True:
        encoded = enc.encode(string)    
        print(f"Number of tokens: {len(encoded)}")
        if len(encoded) > 100000: # like, WAY too long
            string = string[-100000:] # get the last 100k chars
        elif len(encoded) > max_tokens:
            print("Message too long, slicing it down")
            string = string[:-10000] # remove the last 10k chars to shorten it
        else:
            return string

def describe_file(file_path):
    """Reads a file and gets a description of it from an LLM"""
    print(f"Describing file: {file_path}")

    stat_info = os.stat(file_path)
    inode = stat_info.st_ino

    # have we previously described this file?
    metadata_path = f"db/{str(inode)}.json"
    if(os.path.exists(metadata_path)):
        print(f"Already have a description for file: {file_path}")
        with open(metadata_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data['description']

    # we haven't, so read it in and describe it
    reader = SimpleDirectoryReader(input_files=[file_path])
    documents = reader.load_data()
    if (len(documents) == 0):
        print(f"Failed to load document for file: {file_path}")
        return None
    document = documents[0]

    llm = OpenAI(model="gpt-4o")
    mm_llm = OpenAIMultiModal(model="gpt-4o")

    if isinstance(document, ImageDocument):
        response = mm_llm.complete(
            prompt="""Describe the contents of this file, and suggest some possible categories 
            that it might fit into. Some categories might include 'screenshot', 'diagram', 'illustration'""",
            image_documents=documents
        )
        print("Image document response:")
        print(response)
    elif isinstance(document, Document):
        fit_text = sliceUntilFits(document.text, 10000) # fit this into 10k tokens or so
        
        response = llm.complete(
            prompt=f"""Describe the contents of this file, and suggest some possible categories 
            that it might fit into. Some categories might include 'blog post', 'text', 'code', 'data'.
            The text of the document follows:
            {fit_text}"""
        )
        print("Text document response:")
        print(response)

    # save the description to a file
    with open(metadata_path, 'w', encoding='utf-8') as file:
        json.dump({'description': str(response)}, file)
    return str(response)

## TODO: update to understand get_files returns paths now
def describe_files(folder):
    file_paths = get_files_in_folder(folder)
    for file_path in file_paths:
        description = describe_file(file_path)
        # TODO: the stat stuff should probably be in here instead

def categorize_file(description,existing_categories):
    llm = OpenAI(model="gpt-4o")

    prompt = f"""You are sorting files into categories. Below is a list of categories you have 
        already used (there might be none):
        
        {json.dumps(list(existing_categories.keys()), indent=4, sort_keys=True)}

        Now, the following is a description of a new file we want to add to the set. It includes some suggested
        categories for the file based on its contents. Return a suggested category for the file. You should have 
        a bias towards putting files into categories that already exist, but if there are no good categories you can
        return a new one. The file appears between --- and --- below:

        ---
        {description}
        ---

        Return JUST the category name and nothing else.
    """
    response = llm.complete(prompt)
    return str(response)

def recategorize_file_narrower(description,existing_categories):
    llm = OpenAI(model="gpt-4o")

    prompt = f"""You are sorting files into categories. Below is a list of categories you have already used:
        
        {json.dumps(list(existing_categories.keys()), indent=4, sort_keys=True)}

        Now, the following is a description of a new file we want to add to the set. It includes some suggested
        categories for the file based on its contents. Previously, you categorized this file into too broad a category, 
        so when you try to categorize it this time be more specific than the existing categories are. The file appears between --- and --- below:

        ---
        {description}
        ---

        Return JUST the category name and nothing else.
    """
    response = llm.complete(prompt)
    return str(response)

def recategorize_file_broader(description,existing_categories):
    llm = OpenAI(model="gpt-4o")

    prompt = f"""You are sorting files into categories. Below is a list of categories you have already used:
        
        {json.dumps(list(existing_categories.keys()), indent=4, sort_keys=True)}

        Now, the following is a description of a new file we want to add to the set. It includes some suggested
        categories for the file based on its contents. Previously, you categorized this file into too small a category, 
        so when you try to categorize it this time be a bit more general, favoring one of the existing categories. The file appears between --- and --- below:

        ---
        {description}
        ---

        Return JUST the category name and nothing else.
    """
    response = llm.complete(prompt)
    return str(response)

def categorize_file_list(file_paths,categorized, recategorize=None):
    for file_path in file_paths:
        print(f"Categorizing: {file_path}")
        stat_info = os.stat(file_path)
        inode = stat_info.st_ino
        metadata_path = f"db/{str(inode)}.json"
        with open(metadata_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        if recategorize == "broader":
            category = recategorize_file_broader(data['description'], categorized)
        if recategorize == "narrower":
            category = recategorize_file_narrower(data['description'], categorized)
        else:
            category = categorize_file(data['description'], categorized)
        print(f"Suggested category: {category}")
        # add the inode to the category tree
        if (category in categorized):
            categorized[category].append(file_path)
        else:
            categorized[category] = [file_path]
    print(json.dumps(categorized, indent=4, sort_keys=True))
    return categorized

def categorize_files(folder):
    categorized = {}
    # find all the files we have descriptions of and do a first pass
    file_paths = get_files_in_folder(folder)
    described_file_paths = []
    for file_path in file_paths:
        stat_info = os.stat(file_path)
        inode = stat_info.st_ino

        # have we previously described this file? If not, we can't categorize it
        metadata_path = f"db/{str(inode)}.json"
        if(os.path.exists(metadata_path)):
            described_file_paths.append(file_path)
    categorized = categorize_file_list(described_file_paths, categorized)
    # FIXME: this assumes there's only one folder ever
    with open("db/categorized_paths.json", 'w', encoding='utf-8') as file:
        json.dump(categorized, file)

def recategorize_files_once(categorized):
    total_files = sum(len(v) for v in categorized.values())
    original_categories = categorized.copy()
    for category in original_categories:
        if len(original_categories[category]) < MIN_FILES_PER_CATEGORY:
            print(f"Category {category} has fewer than {MIN_FILES_PER_CATEGORY} files. Recategorizing.")
            files_to_recategorize = categorized[category]
            del categorized[category]
            categorized = categorize_file_list(files_to_recategorize, categorized, recategorize="broader")
        elif len(original_categories[category]) > (total_files / 5):
            print(f"Category {category} has more than 20% of the files. Recategorizing.")
            files_to_recategorize = categorized[category]
            del categorized[category]
            categorized = categorize_file_list(files_to_recategorize, categorized, recategorize="narrower")
    return categorized

def needs_recategorization(categorized):
    total_files = sum(len(v) for v in categorized.values())
    for category in categorized:
        if len(categorized[category]) < MIN_FILES_PER_CATEGORY:
            return True
        if len(categorized[category]) > (total_files / 5):
            return True
    return False

def recategorize_files():
    with open("db/categorized_paths.json", 'r', encoding='utf-8') as file:
        categorized = json.load(file)
    passes = 0
    while needs_recategorization(categorized) and passes < 5:
        categorized = recategorize_files_once(categorized)
        passes += 1
    print("---- All done: ----")
    print(json.dumps(categorized, indent=4, sort_keys=True))
    with open("db/categorized_paths.json", 'w', encoding='utf-8') as file:
        json.dump(categorized, file)

def move_files(base_path):
    with open("db/categorized_paths.json", 'r', encoding='utf-8') as file:
        categorized = json.load(file)
    auto_generated_folders = []
    for category in categorized:
        category_path = f"{base_path}/{category} (Auto)"
        if not os.path.exists(category_path):
            os.makedirs(category_path)
        for file_path in categorized[category]:
            file_name = file_path.split("/")[-1]
            new_path = f"{category_path}/{file_name}"
            os.rename(file_path, new_path)
            print(f"Moved {file_path} to {new_path}")
            auto_generated_folders.append(category_path)
    # clean up any empty folders
    with open("db/auto_generated_folders.json", 'r', encoding='utf-8') as file:
        previous_auto_generated_folders = json.load(file)
    # get all the folders that are in previous_auto_generated_folders but not in auto_generated_folders
    folders_to_remove = [folder for folder in previous_auto_generated_folders if folder not in auto_generated_folders]
    for folder in folders_to_remove:
        os.rmdir(folder)
        print(f"Removed empty folder: {folder}")
    # write the auto-generated folders list
    with open("db/auto_generated_folders.json", 'w', encoding='utf-8') as file:
        json.dump(auto_generated_folders, file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Describe or categorize the files in a folder")
    parser.add_argument("path", help="The path to the folder.")
    parser.add_argument("--describe", action="store_true", help="Describe the contents of the directory.")
    parser.add_argument("--categorize", action="store_true", help="Categorize the contents of the directory.")
    parser.add_argument("--recategorize", action="store_true", help="Recategorize the contents of the directory.")
    parser.add_argument("--move", action="store_true", help="Move files into categorized folders.")
    
    args = parser.parse_args()
    if args.describe:
        describe_files(args.path)
    elif args.categorize:
        categorize_files(args.path)
    elif args.recategorize:
        recategorize_files()
    elif args.move:
        move_files(args.path)
