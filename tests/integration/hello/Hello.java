import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;

public class Hello {
    public static void main(String[] args) throws IOException {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        int count = Integer.parseInt(reader.readLine().trim());
        StringBuilder output = new StringBuilder();
        for (int i = 0; i < count; i++) {
            output.append("Ola ").append(reader.readLine().trim()).append("!\n");
        }
        System.out.print(output);
    }
}
