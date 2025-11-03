import time
import math
import getopt
import re
import sys
import copy
import urllib.parse
from dotenv import load_dotenv
from selenium.webdriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select

sleep_time_between_pages = 4
cards_header = ["Name", "Treatment", "Name Without Treatment", "Set", "Rarity", "Quantity", "Condition/Language", "Price", "Image URL", "Product URL"]
wanted_cards_header = ["Quantity", "Name"]
found_cards_header = ["Name"]

global_cards_checked_from_beginning = []
#accpetable items
#[ "name", "link", "price", "market_price", "quantity", "printing", "quantity_to_get", "total_price" ]
global_stores = []
#acceptable items
#[ "seller", "sellerid", "total_cost", "cards_scanned", "checked_inventory", "score" ]


def load_desired_cards_from_file(file_location):
    """Attempts to load the desired cards to search against store inventory from a txt file hat is space delimited. Format is: {qty} {name}. Reference example in desired_cards_example.txt.

    Args:
        file_location (string): file_location for wanted cards text file. 

    Returns:
        list: list of desired cards with quantity and name as fields.
    """
    desired_cards = []

    if not file_location:
        return desired_cards

    try:
        with open(file_location, "r") as f:
            file_content = f.read()

        if not file_content:
            print("no data found in file " + file_location)
            return desired_cards
        
        # format in file is {qty} {card name}
        cards = file_content.splitlines()
        for card in cards:
            card_parts = card.split(None, 1)

            desired_card = [card_parts[0], card_parts[1]]
            desired_cards.append(desired_card)

        return desired_cards

    except Exception as e:
        #print(e)
        return desired_cards

def setup_selenium_driver(headless):
    """Sets up the Selenium driver based on a variety of settings.
    """
    options = ChromeOptions()

    # Does not like headless due to out of bounds, will need to look into this. Trying the headless=new flag for full featured Chrome, but new headless implementation
    # Headless=new requires Chrome 109. Need to add the Chrome installation dependency.
    if headless:
        options.add_argument("--headless=new")

    options.add_argument('--log-level=3')
    options.add_argument('--start-maximized')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    
    driver = Chrome(options=options)

    return driver

def check_for_multiple_cards(driver,multiples):
    cards = []
    for card in multiples:
        driver.get(card["link"])
        WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "section.listing-item")))
        time.sleep(0.5)

        #get the universal things like foil vs non foil market price
        market_prices = driver.find_elements(By.CSS_SELECTOR, "span.near-mint-table__price")
        non_foil_market_price = market_prices[0].text.strip().replace("$","").replace(",","")
        if len(market_prices) > 1:
            foil_market_price = market_prices[1].text.strip().replace("$","").replace(",","")
        else:
            #we should never get here, but it happened once. dunno how
            foil_market_price = non_foil_market_price

        listings = driver.find_elements(By.CSS_SELECTOR, "section.listing-item")
        #find all the different listings. could be near mint foil, lightly played foil, moderately played foil...
        for listing in listings:
            try:
                listing_div = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info span")
            except:
                listing_div = None

            if listing_div:

                try:
                    price = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info__price").text.strip()
                    price = price.replace("$","").replace(",","")
                except:
                    continue
                    price = None

                try:
                    quality = listing.find_element(By.CSS_SELECTOR, "h3.listing-item__listing-data__info__condition").text.strip()
                except:
                    continue

                try:
                    quantity = listing.find_element(By.CSS_SELECTOR, ".add-to-cart__available").text
                    quantity = "".join(char for char in quantity if char.isdigit())
                except:
                    continue
                    
                if "foil" in quality:
                    market_price = foil_market_price
                else:
                    market_price = non_foil_market_price

            cards.append({
                "name": card["name"],
                "link": card["link"],
                "price": price,
                "market_price": market_price,
                "quantity": quantity,
                "printing": card["printing"],
                "set": card["set"],
                "quality": quality
            })

    return cards

def search_card(driver,card,store_url):
    """searches for a card and returns a list of valid cards. can have multiple cards because of various printings"""

    def either_element_present(driver):
        results = driver.find_elements(By.CSS_SELECTOR, "div.search-result")
        blank = driver.find_elements(By.CSS_SELECTOR, "div.blank-slate")
        if results:
            return "results"
        elif blank:
            return "blank"
        else:
            return False  # keep waiting
    
    #open the page
    if not store_url:
        url = "https://www.tcgplayer.com/search/magic/product?productLineName=Magic%3A+The+Gathering&q=" + urllib.parse.quote(card[1])
    else:
        url = store_url

    driver.get(url)
    found = WebDriverWait(driver, 10).until(either_element_present)
    time.sleep(0.5)

    if found == "blank":
        return None

    #get search results
    results = driver.find_elements(By.CSS_SELECTOR, "div.search-result")
    cards = []
    multiples = []
    for result in results:
        try:
            og_name = result.find_element(By.CSS_SELECTOR, ".product-card__title").text
            name = re.sub(r"\s*\(.*?\)\s*", "", og_name).strip()
            if card[1].lower() != name.lower():
                continue
            printing = " ".join(p.strip() for p in re.findall(r"\((.*?)\)", og_name))
        except:
            continue
            name = "Unknown"
            printing = ""

        try:
            quantity = result.find_element(By.CSS_SELECTOR, ".inventory__listing-count").text
            quantity = "".join(char for char in quantity if char.isdigit())
        except:
            continue
            quantity = "N/A"

        try:
            link = result.find_element(By.TAG_NAME, "a").get_attribute("href")
        except:
            continue
            link = None

        try:
            price = result.find_element(By.CSS_SELECTOR, ".inventory__price-with-shipping").text
            price = price.replace("$","").replace(",","")
        except:
            #im not sure how we get here
            print("couldnt find the price for: " + link)
            continue
            price = "N/A"

        try:
            market_price = result.find_element(By.CSS_SELECTOR, ".product-card__market-price--value").text
            market_price = market_price.replace("$","").replace(",","")
        except:
            #this should never happen but it happened once
            print("couldnt find market price for: " + link)
            continue
            market_price = "N/A"        
        
        try:
            mtg_set = result.find_element(By.CSS_SELECTOR, "div.product-card__set-name__variant").text
        except:
            mtg_set = "N/A"

        card_to_append = {
                "name": name,
                "link": link,
                "price": price,
                "market_price": market_price,
                "quantity": quantity,
                "printing": printing,
                "set": mtg_set,
                "quality": ""
            }
        #if theres more than 1 quantity and we are on a store page, the store may have more than 1 listing that gets reported as the same card. eg foil/non-foil
        if int(quantity) > 1 and store_url:
            multiples.append(card_to_append)
        else:
            cards.append(card_to_append)
    
    cards_to_append = check_for_multiple_cards(driver,multiples)
    for card in cards_to_append:
        cards.append(card)
    return cards

def find_lowest_price_card(cards, use_market):
    #find the lowest price card
    lowest_price = "9999.99"
    lowest_price_card = None
    for found in cards:
        if use_market:
            found_price = found["market_price"]
        else:
            found_price = found["price"]
        if found_price < lowest_price:
            lowest_price = found_price
            lowest_price_card = found

    return lowest_price_card

def get_total_pages(driver):
    try:
        # Find all the page number elements
        WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.tcg-pagination__pages a.tcg-button")))
        time.sleep(0.5)
        pages = driver.find_elements(By.CSS_SELECTOR, "div.tcg-pagination__pages a.tcg-button")

        page_numbers = []
        for el in pages:
            text = el.text.strip()
            if text.isdigit():
                page_numbers.append(int(text))

        if page_numbers:
            return max(page_numbers)
        else:
            return 1  # Only one page of results
    except Exception as e:
        print("Error getting page count:", e)
        return 1

def check_reasonable_price(card, listing_price):
    """Checks to see if the listing price is within $3 of the market price for the card."""
    market_price = float(card["market_price"])
    listing_price_float = float(listing_price)
    if listing_price_float - market_price < 2.50 and market_price < 10.00:
        return True
    elif listing_price_float - market_price < 4.00 and market_price < 50.00:
        return True
    elif listing_price_float - market_price < 6.00 and market_price >= 50.00:
        print("large price card reccomend manually checking")
        print_card(card)
        return True
    else:
        return False

def find_stores(driver,card):
    """finds all the stores with free shipping over $5 for the given card"""
    #go to the card page
    driver.get(card["link"])

    WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.tcg-input-select__trigger")))
    time.sleep(0.5)
    triggers = driver.find_elements(By.CSS_SELECTOR, "div.tcg-input-select__trigger")
    triggers[1].click()
    
    time.sleep(0.5)  # tiny pause for dropdown animation
    
    # Find the desired item in the dropdown list
    items = driver.find_elements(By.CSS_SELECTOR, "ul.tcg-base-dropdown li.tcg-base-dropdown__item")
    for item in items:
        if item.text.strip() == str(50):
            item.click()
            break
    
    pages = get_total_pages(driver)
    #print("Total pages of results for card '" + card["name"] + "': " + str(pages))

    #paginate through all pages
    for page in range(1, pages + 1):
        paginated_url = card["link"] + "&page=" + str(page)
        #skip page 1 since we're already on it
        if page > 1:
            driver.get(paginated_url)
        WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "section.listing-item")))
        time.sleep(0.5)

        listings = driver.find_elements(By.CSS_SELECTOR, "section.listing-item")
        #find all stores with free shipping over $5
        for listing in listings:
            try:
                listing_div = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info span")
            except:
                #why are we here?
                print("no listing div??")
                listing_div = None

            # Check for free shipping link
            has_free_shipping_link = False
            # Case 1: Free shipping over $5
            if listing_div:
                try:
                    # Case 1: Free shipping over $5
                    free_link = listing_div.find_element(By.CSS_SELECTOR, "a.free-shipping-over-min")
                    if "Over $5" in free_link.text and not "Over $50" in free_link.text:
                        has_free_shipping_link = True
                except:
                    # Case 2: Shipping included
                    try:
                        shipping_links = listing.find_elements(By.TAG_NAME, "a")

                        for link in shipping_links:
                            link_text = link.text.strip()
                            href = link.get_attribute("href") or ""

                            if "Included" in link_text or "Shipping-Included" in href:
                                has_free_shipping_link = True
                                break
                    except:
                        pass

            # Only keep if qualifies
            if has_free_shipping_link:
                try:
                    seller = listing.find_element(By.CSS_SELECTOR, "a.seller-info__name").text.strip()
                    sellerid = listing.find_element(By.CSS_SELECTOR, "a.seller-info__name").get_attribute("href").split("/")[-1]
                    already_in_stores = False
                    for store in global_stores:
                        if store["sellerid"] == sellerid:
                            already_in_stores = True
                            break
                    if already_in_stores:
                        continue
                except:
                    print("why would we be here??")
                    continue
                    sellerid = None
                    seller = None

                try:
                    price = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info__price").text.strip()
                    price = price.replace("$","").replace(",","")
                except:
                    print("why would we be here?")
                    continue
                    price = None

                #only add if the price is within $3 of market price
                if check_reasonable_price(card, price):
                    global_stores.append({
                        "seller": seller,
                        "sellerid": sellerid,
                        "checked_inventory": False,
                        "score": 0.0
                    })

    return

def check_store_inventory(driver,store,desired_cards):
    """Checks the store inventory for the desired cards. Returns a list of found cards."""
    cards_scanned = []
    #make sure we dont rescrape the inventory to save time
    if store["checked_inventory"] == True:
        return store
    
    store_url = "https://www.tcgplayer.com/search/magic/product?productLineName=magic&seller=" + store["sellerid"] + "&q="

    #loop through all the cards we want on this particular store
    for desired_card in desired_cards:
        url = store_url + urllib.parse.quote(desired_card[1])
        cards = search_card(driver, desired_card, url) #this is a list of all the cards that are valid printings
        if cards is None:
            continue
        cards.sort(key=lambda x: float(x["price"]))
        amount_needed = int(desired_card[0])
        #go through cards from lowest price to highest
        for card in cards:
            quantity_available = int(card["quantity"])
            #skip if price is more than $3 over market price
            if not check_reasonable_price(card, card["price"]):
                continue
                
            if quantity_available >= amount_needed:
                card["quantity_to_get"] = amount_needed
                card["total_price"] = float(card["price"]) * amount_needed
                if card:
                    cards_scanned.append(card)
                break
            else:
                amount_needed -= quantity_available
                card["quantity_to_get"] = quantity_available
                card["total_price"] = float(card["price"]) * quantity_available
                if card:
                    cards_scanned.append(card)
    store["cards_scanned"] = cards_scanned
    store["total_cost"] = str(sum(card["total_price"] for card in store["cards_scanned"]))
    store["checked_inventory"] = True
    return store

def print_card(card):
    print("Name: " + card["name"])
    print("Link: " + str(card["link"]))
    print("Price: " + card["price"])
    print("Market Price: " + card["market_price"])
    print("Quantity: " + card["quantity"])
    if "quantity_to_get" in card:
        print("Quantity to get: " + str(card["quantity_to_get"]))
    print("Printing: " + card["printing"])
    print("Set: " + card["set"])
    print("-----")
    return

def print_store(store,print_cards):
    print("Store: " + store["seller"])
    print("Store ID: " + store["sellerid"])
    print("Score: " + str(store["score"]))
    print("Total cost of cards to get: $" + str(store["total_cost"]))
    if print_cards:
        print("Possible cards to get:")
        for card in store["cards_scanned"]:
            print_card(card)
    print("--------------------------------------------")
    return

def evaluate_store(store, desired_cards, coverage_weight, efficiency_weight, shipping_weight):
    """
    Evaluate a store based on:
      - coverage: how many desired cards it fulfills
      - efficiency: ratio of market value to actual cost (higher = better)
      - shipping: favor stores above or near the $5 free shipping threshold

    Returns the updated store with `score`, `effective_cost`, and detail metrics.
    """
    covered_cards = 0
    total_cards = 0
    total_cost = 0.0
    total_market = 0.0

    for card in store["cards_scanned"]:
        if any(desired_card[1].lower() == card["name"].lower() for desired_card in desired_cards):
            qty = int(card["quantity_to_get"])
            market = float(card["market_price"])
            price = float(card["price"])
            covered_cards += 1
            total_cards += qty
            total_cost += price * qty
            total_market += market * qty

    if covered_cards == 0 or total_cost == 0:
        store["score"] = 0.0
        return store

    # Coverage ratio (how much of the list this store covers)
    coverage_ratio = covered_cards / len(desired_cards)

    # Efficiency: how close to or below market value
    efficiency = total_market / total_cost

    # Shipping curve:
    # - Smooth logistic curve centered at $5
    # - Below $5 gets <1 multiplier, above $5 gets >1
    shipping_curve = 1 / (1 + math.exp(-1.2 * (total_cost - 5)))
    # Normalize so $5 = 1.0 exactly
    shipping_curve = (shipping_curve - 0.5) * 2  

    # Map from [-1, 1] → [0.8, 1.2] scaling for shipping weight
    shipping_bonus = 1 + (shipping_curve * 0.2 * shipping_weight)

    # Weighted scoring
    score = (coverage_ratio * coverage_weight) + (efficiency * efficiency_weight)
    score *= shipping_bonus

    # Store extra details
    store["score"] = float(score)
    store["total_cost"] = total_cost
    return store

def reset_tcgplayer_state(driver):
    # 1. Load the domain so JS can access its local/session storage
    driver.get("https://www.tcgplayer.com")
    # small wait to ensure the app bootstraps
    time.sleep(0.5)

    # 2. Clear local/session storage on that origin
    try:
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except Exception as e:
        # If this fails, we'll fall back to other methods below
        print("execute_script clear failed:", e)

    # 3. Delete cookies (clears cookies for all domains in the session)
    try:
        driver.delete_all_cookies()
    except Exception as e:
        print("delete_all_cookies failed:", e)

    # 4. Navigate to a blank page and then to the search URL (cache-buster optional)
    driver.get("about:blank")
    time.sleep(1)

def adjust_quantity_to_get(store, desired_cards):
    new_store_inventory = []
    
    for card in store["cards_scanned"]:
        # find the desired card that matches this store card
        matching_desired = None
        for desired_card in desired_cards:
            if desired_card[1].lower() == card["name"].lower():
                matching_desired = desired_card
                break
        
        if matching_desired:
            qty_needed = int(matching_desired[0])
            qty_available = int(card["quantity"])
            card["quantity_to_get"] = str(min(qty_needed, qty_available))
        else:
            # If card is not in desired_cards, leave quantity_to_get as is
            card["quantity_to_get"] = "0"
        
        new_store_inventory.append(card)
    
    store["cards_scanned"] = new_store_inventory
    return store

def build_possible_cart(driver,desired_cards_og, coverage_weight, efficiency_weight, shipping_weight):
    cart_stores = []
    found_cards = []
    unmodified_desired_cards = copy.deepcopy(desired_cards_og)
    desired_cards = copy.deepcopy(desired_cards_og)

    for parent_desired_card in unmodified_desired_cards:
        double_break = False
        #make sure we haven't already found this card in a previous store
        for found_card in found_cards:
            if parent_desired_card[1].lower() == found_card[1].lower():
                if int(parent_desired_card[0]) <= int(found_card[0]):
                    double_break = True
                    break
        if double_break:
            continue
        
        #clear cache in case we are on a store page
        reset_tcgplayer_state(driver)
        already_checked = False
        for name in global_cards_checked_from_beginning:
            if parent_desired_card[1] == name:
                already_checked = True
        if not already_checked:
            global_cards_checked_from_beginning.append(parent_desired_card[1])
            cards = search_card(driver, parent_desired_card,"")
            if cards is None:
                print("couldnt find cards: " + parent_desired_card[1])
                time.sleep(20)
                quit()

            lowest_card = find_lowest_price_card(cards, True)

            if lowest_card is None:
                print("couldnt find card: " + parent_desired_card[1])
                print(cards.__len__())
                time.sleep(20)
                quit()

            #use the lowest priced card and then try to get similarly priced printings to check those too
            for card in cards:
                if float(card["market_price"]) <= 2.0+float(lowest_card["market_price"]):
                    find_stores(driver, card)
            # Print all stores with free shipping over $5 for testing
            #print("checking the stores we found on the card page")
            #print_card(card)
        
        found_enough = False
        while not found_enough:
            evaluation_score = 0.0
            best_store = None
            
            if global_stores == []:
                print("No stores found for card: " + parent_desired_card[1])
                quit()

            #go through all stores and find the one with the best evaluation score
            for store in global_stores:
                already_in_cart = False
                for cart_store in cart_stores:
                    if store["sellerid"] == cart_store["sellerid"]:
                        already_in_cart = True
                        break
                if already_in_cart:
                    continue
                
                found_store = check_store_inventory(driver, store, desired_cards)
                found_store = adjust_quantity_to_get(found_store,desired_cards)
                found_store = evaluate_store(found_store, desired_cards, coverage_weight, efficiency_weight, shipping_weight)
                if evaluation_score < found_store["score"]:
                    evaluation_score = found_store["score"]
                    best_store = found_store
            
            if not best_store:
                print("couldnt find a best store... why?")
                for desired_card in desired_cards:
                    print(desired_card)
                exit()

            print("Adding store to possible cart:")
            print_store(best_store,True)
            cart_stores.append(best_store)
            #remove the cards we found from the desired cards list
            for card in best_store["cards_scanned"]:
                for i in range(desired_cards.__len__()):
                    if card["name"].lower() == desired_cards[i][1].lower():
                        amount_needed = int(desired_cards[i][0])
                        amount_found = int(card["quantity_to_get"])
                        #check if we found all we need for this card
                        already_in_found = False
                        card_in_found = None
                        for j in range(found_cards.__len__()):
                            if found_cards[j][1].lower() == card["name"].lower():
                                found_cards[j][0] = str(int(found_cards[j][0]) + amount_found)
                                card_in_found = found_cards[j]
                                already_in_found = True
                                break
                        if not already_in_found:
                            found_cards.append([amount_found, card["name"]])
                            card_in_found = [amount_found, card["name"]]
                        if parent_desired_card[1].lower() == card_in_found[1].lower() and int(parent_desired_card[0]) <= int(card_in_found[0]):
                            found_enough = True
                        desired_cards[i][0] = str(max(0, amount_needed - amount_found))
                        print("added this card to the cart: " + str(amount_found) + " " + desired_cards[i][1])

            #trim off the desired cards that have no quantity left
            desired_cards = [dc for dc in desired_cards if int(dc[0]) > 0]
            print("things still to look for: ")
            print(desired_cards)
            print("-----")
            if desired_cards == []:
                return cart_stores
    return cart_stores

def add_potential_cart_to_cart(driver,stores):
    for store in stores:
        for card in store["cards_scanned"]:
            if int(card["quantity_to_get"]) > 0:
                driver.get(card["link"])
                WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "section.listing-item")))
                time.sleep(0.5)
                #WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "select[data-testid='mp-select__UpdateProductQuantity']")))
                #WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button[data-testid^='add-to-cart__submit--']")))
                #make sure we dont add the thing by tcg direct as stores can contain both from tcg direct and not
                listings = driver.find_elements(By.CSS_SELECTOR, "section.listing-item")
                #pick the one without tcgplayer direct
                for listing in listings:
                    listing_div = listing.find_element(By.CSS_SELECTOR, "div.listing-item__listing-data__info span")
                    if listing_div:
                        try:
                            has_direct_icon = listing_div.find_element(By.CSS_SELECTOR, "img.filterIcon iconDirect")
                            if not has_direct_icon:
                                #make sure this is the same card quality
                                if card["quality"] != "":
                                    quality = listing.find_element(By.CSS_SELECTOR, "h3.listing-item__listing-data__info__condition").text.strip()
                                    print("quality is: " + quality)
                                    if card["quality"] != quality:
                                        #this aint the same one we picked. find the next listing
                                        continue
                                qty_dropdown = listing.find_element(By.CSS_SELECTOR, "select[data-testid='mp-select__UpdateProductQuantity']")
                                select = Select(qty_dropdown)
                                #choose how many
                                select.select_by_value(card["quantity_to_get"])
                                button = listing.find_element(By.CSS_SELECTOR, "button[data-testid^='add-to-cart__submit--']")
                                #click button
                                driver.execute_script("arguments[0].click();", button)
                                break
                        except:
                            try:
                                #if we dont have the direct icon, we can get here
                                #make sure this is the same card quality
                                if card["quality"] != "":
                                    quality = listing.find_element(By.CSS_SELECTOR, "h3.listing-item__listing-data__info__condition").text.strip()
                                    print("quality is: " + quality)
                                    if card["quality"] != quality:
                                        #this aint the same one we picked. find the next listing
                                        continue
                                qty_dropdown = listing.find_element(By.CSS_SELECTOR, "select[data-testid='mp-select__UpdateProductQuantity']")
                                select = Select(qty_dropdown)
                                #choose how many
                                select.select_by_value(card["quantity_to_get"])
                                button = listing.find_element(By.CSS_SELECTOR, "button[data-testid^='add-to-cart__submit--']")
                                #click button
                                driver.execute_script("arguments[0].click();", button)
                                break
                            except Exception as e:
                                print(f"Error adding card from {card["link"]}: {e}")

                #wait to make sure it was added to cart
                time.sleep(1)
                
    return

def main(argv):
    want_file_location = ""
    headless = False

    try:
        opts, args = getopt.getopt(argv,"w:h",["want-file-location=","headless-flag"])
    except getopt.GetoptError:
        print('tcg_player_searcher.py -w <want-file-location> -h <headless-flag>')
        print("want-file-location is the file location for a list of card names (in a text file) that you're looking to find for the store")
        print("headless-flag is the Selenium/Chrome flag to run headless.")
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-w", "--want-file-location"):
            want_file_location = arg
        if opt in ("-h", "--headless-flag"):
            #TODO doesnt work yet
            headless = True 

    if not want_file_location:
        print("Please provide want file. Exiting.")
        sys.exit(2)

    load_dotenv()

    desired_cards = []
    if want_file_location:
        desired_cards = load_desired_cards_from_file(want_file_location)

    start = time.time()

    num_desired_cards = 0
    for desired_card in desired_cards:
        num_desired_cards += int(desired_card[0])

    print("Total desired cards to search for: " + str(num_desired_cards))
    

    driver = setup_selenium_driver(headless)

    cart_stores1 = build_possible_cart(driver, desired_cards,25,2,3)
    cart_stores2 = build_possible_cart(driver, desired_cards,5,10,0.5)
    cart_stores3 = build_possible_cart(driver, desired_cards,15,8,2)

    price_over_whole_cart=0.00
    number_of_stores=0
    print("Possible stores to buy from cart 1:")
    print()
    for store in cart_stores1:
        print_store(store,True)
        number_of_stores += 1
        price_over_whole_cart += store["total_cost"]
    print("Total Cost: " + str(price_over_whole_cart) + " over " + str(number_of_stores) + " stores")
    price_over_whole_cart=0.00
    number_of_stores=0
    
    print("Possible stores to buy from cart 2:")
    print()
    for store in cart_stores2:
        print_store(store,True)
        number_of_stores += 1
        price_over_whole_cart += store["total_cost"]
    print("Total Cost: " + str(price_over_whole_cart) + " over " + str(number_of_stores) + " stores")
    price_over_whole_cart=0.00
    number_of_stores=0

    print("Possible stores to buy from cart 3:")
    print()
    for store in cart_stores3:
        print_store(store,True)
        number_of_stores += 1
        price_over_whole_cart += store["total_cost"]
    print("Total Cost: " + str(price_over_whole_cart) + " over " + str(number_of_stores) + " stores")
    
    #store_card_inventory = scrape_store_by_sets(store_front_url)
    #found_cards_in_inventory_df = find_wanted_cards_dataframe(store_card_inventory, desired_cards)

    #write_to_excel(store_card_inventory, desired_cards, found_cards_in_inventory_df)

    end = time.time()
    elapsed_time = end - start
    #total_cards_scraped = len(store_card_inventory)
    #cards_scraped_per_second = total_cards_scraped / elapsed_time

    print("Script run time: " + str(elapsed_time))
    #print("Cards scraped: " + str(total_cards_scraped))
    #print("Cards scraped per second: " + str(cards_scraped_per_second))

    #get which cart the user likes
    response = str(input("Please select which cart you like: "))
    if response == "1":
        add_potential_cart_to_cart(driver,cart_stores1)
    if response == "2":
        add_potential_cart_to_cart(driver,cart_stores2)
    if response == "3":
        add_potential_cart_to_cart(driver,cart_stores3)

    #wait for the user to check out or copy cart or something
    input("Press enter when finished.")
    print("cleaning up")
    driver.quit()

if __name__ == "__main__":
    main(sys.argv[1:])