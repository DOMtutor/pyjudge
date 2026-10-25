#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    char line[1 << 16];
    if (!fgets(line, sizeof line, stdin)) {
        return 1;
    }
    int count = atoi(line);
    for (int i = 0; i < count && fgets(line, sizeof line, stdin); i++) {
        char *name = line;
        while (isspace((unsigned char) *name)) {
            name++;
        }
        size_t length = strlen(name);
        while (length > 0 && isspace((unsigned char) name[length - 1])) {
            name[--length] = '\0';
        }
        printf("Ola %s!\n", name);
    }
    return 0;
}
