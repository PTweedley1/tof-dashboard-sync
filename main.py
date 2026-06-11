from sync import triple_whale

def main():
    print("=== TOF Dashboard Sync ===\n")
    triple_whale.sync()
    # shopify.sync()    # coming soon
    # recharge.sync()   # coming soon
    # ga4.sync()        # coming soon
    # justuno.sync()    # coming soon
    print("\nDone.")

if __name__ == "__main__":
    main()
