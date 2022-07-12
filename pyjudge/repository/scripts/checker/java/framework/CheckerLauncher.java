package framework;

import java.io.FileInputStream;
import java.lang.reflect.Constructor;
import java.util.InputMismatchException;

public class CheckerLauncher {
  public static void main(String[] args) {
    if (args.length != 3) {
      System.exit(1);
      return;
    }

    AbstractChecker checker = null;
    try {
      String checkerName = args[0];
      Class<?> clazz = Class.forName(checkerName);
      Constructor<?> ctor = clazz.getConstructor();
      Object object = ctor.newInstance();
      checker = (AbstractChecker) object;
      checker.setTestcaseInput(new FileInputStream(args[1]));
      checker.setTestcaseOutputSc(new FileInputStream(args[2]));
      checker.setProgramSc(System.in);
    } catch (Exception e) {
      System.err.println("Could not start checker.");
      e.printStackTrace();
      System.exit(0);
    }

    // catch those exceptions that are judge errors, i.e. test case input or
    // output incorrect or not set
    try {
      checker.check();
    } catch (InputMismatchException e) {
      System.err.println("End checking because of input mismatch: " + e.getMessage());
      System.exit(0);
    } catch (Exception e) {
      System.err.println("The checker crashed with an exception.");
      e.printStackTrace();
      System.exit(0);
    }
  }
}
