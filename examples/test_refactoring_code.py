def process_data(data):
    """
    偶数を2倍にして、10より大きいものを集める
    """
    return [item * 2 for item in data if item % 2 == 0 and item * 2 > 10]

my_data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
processed = process_data(my_data)
print(processed)
