import sqlite3

conn = sqlite3.connect('test.db')

print("Opened database successfully");

"""conn.execute('''CREATE TABLE SNDND
         (ID  INTEGER PRIMARY KEY AUTOINCREMENT,
         DATE           DATE    NOT NULL,
         IsSent            INT     NOT NULL
        );''')
print("Table created successfully")
"""



conn.execute('''INSERT INTO SNDND (DATE,IsSent) VALUES (date('now'),1)''');



conn.close()